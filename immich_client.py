"""Immich HTTP calls with timeouts, reporting failures as ImmichError.

The frame gives up on /download after 50 s (HTTP_TIMEOUT in the firmware).
Every call here stays inside that so the device gets a status code it can act
on instead of a dropped connection.
"""

import time

import requests

# Immich on the LAN answers in well under a second; these only matter when it
# is down or stalls after accepting the connection.
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 20
# An original can be a RAW file of tens of megabytes. The read timeout covers
# each chunk only, so a trickling connection could outlast the frame: the
# whole body also gets a deadline.
DOWNLOAD_TIMEOUT = (CONNECT_TIMEOUT, 15)
DOWNLOAD_DEADLINE = 25
DOWNLOAD_CHUNK_SIZE = 8 * 1024
PREVIEW_TIMEOUT = (CONNECT_TIMEOUT, 15)
SEARCH_PAGE_SIZE = 1000
# Budget for every Immich call of one /download together. Per-call timeouts
# alone add up to well over the frame's 50 s; the rest is left for processing.
REQUEST_BUDGET = 40


class ImmichError(Exception):
    """Carries the message and the HTTP status /download should report."""

    def __init__(self, message, status=500):
        super().__init__(message)
        self.message = message
        self.status = status


def new_deadline():
    """A monotonic deadline REQUEST_BUDGET seconds from now, shared by one request's calls."""
    return time.monotonic() + REQUEST_BUDGET


def _clamp_timeout(timeout, deadline):
    """Shrink a (connect, read) timeout to what is left before deadline; 504 if nothing is."""
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ImmichError('Immich took too long overall', 504)
    connect, read = timeout
    return (min(connect, remaining), min(read, remaining))


def call(method, url, headers, deadline=None, **kwargs):
    """requests.request() with timeouts; transport failures become 504/502."""
    kwargs['timeout'] = _clamp_timeout(kwargs.get('timeout', (CONNECT_TIMEOUT, READ_TIMEOUT)), deadline)
    try:
        return requests.request(method, url, headers=headers, **kwargs)
    except requests.Timeout as error:
        raise ImmichError(f'Immich did not answer in time: {error}', 504) from error
    except requests.RequestException as error:
        raise ImmichError(f'Could not reach Immich: {error}', 502) from error


def resolve_album_id(base_url, headers, album_name, deadline=None):
    """The id of the album called album_name; 404 if there is none."""
    response = call('GET', f'{base_url}/api/albums', headers, deadline, params={'withoutAssets': 'true'})
    if response.status_code != 200:
        print(f'[ERROR] GET /api/albums → HTTP {response.status_code}: {response.text[:500]}')
        raise ImmichError(f'Failed to fetch albums (Immich returned {response.status_code})', 502)

    album_id = next((item['id'] for item in response.json() if item['albumName'] == album_name), None)
    if not album_id:
        raise ImmichError('Album not found', 404)
    return album_id


def list_album_assets(base_url, headers, album_id, deadline=None):
    """Every image in the album, with EXIF.

    Immich v3: GET /api/albums/{id} no longer returns 'assets', so this pages
    through POST /api/search/metadata. Videos are left out; handed to PIL they
    only fail later with "cannot identify image file".
    """
    assets = []
    page = 1
    while True:
        body = {'albumIds': [album_id], 'type': 'IMAGE', 'size': SEARCH_PAGE_SIZE, 'page': page, 'withExif': True}
        response = call('POST', f'{base_url}/api/search/metadata', headers, deadline, json=body)
        if response.status_code != 200:
            raise ImmichError(f'Failed to fetch album details (Immich returned {response.status_code})', 502)

        result = response.json().get('assets', {})
        # Filtered again in case an older server ignores 'type'
        assets.extend(item for item in result.get('items', []) if item.get('type', 'IMAGE') == 'IMAGE')

        next_page = result.get('nextPage')
        if not next_page:
            break
        page = int(next_page)

    if not assets:
        raise ImmichError('No images found in album', 404)
    return assets


def fetch_original(base_url, headers, asset_id, deadline=None):
    """The asset's original bytes, downloaded within DOWNLOAD_DEADLINE seconds (and before deadline)."""
    download_deadline = time.monotonic() + DOWNLOAD_DEADLINE
    if deadline is not None:
        download_deadline = min(download_deadline, deadline)
    response = call(
        'GET',
        f'{base_url}/api/assets/{asset_id}/original',
        headers,
        download_deadline,
        timeout=DOWNLOAD_TIMEOUT,
        stream=True,
    )
    with response:
        if response.status_code != 200:
            raise ImmichError(f'Failed to download image (Immich returned {response.status_code})', 502)
        chunks = []
        try:
            # Small chunks: iter_content returns only once a chunk is full, so the
            # deadline is checked at most one chunk late on a slow connection.
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                chunks.append(chunk)
                if time.monotonic() > download_deadline:
                    raise ImmichError('Downloading the original took too long', 504)
        except requests.RequestException as error:
            raise ImmichError(f'Download from Immich failed: {error}', 502) from error
    return b''.join(chunks)


def fetch_preview(base_url, headers, asset_id, deadline=None):
    """Immich's preview rendering (JPEG or WebP), used when the original cannot be decoded."""
    response = call(
        'GET',
        f'{base_url}/api/assets/{asset_id}/thumbnail',
        headers,
        deadline,
        params={'size': 'preview'},
        timeout=PREVIEW_TIMEOUT,
    )
    if response.status_code != 200:
        raise ImmichError(f'Failed to download preview (Immich returned {response.status_code})', 502)
    return response.content
