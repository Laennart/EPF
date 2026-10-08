"""Tests for the Immich HTTP client and asset decoding.

- Every request has connect/read timeouts that stay inside the frame's 50 s limit
- Transport failures become ImmichError with 504 (timeout) or 502 (unreachable)
- Album listing asks for images only and filters videos out again
- Downloading an original has a deadline for the whole body
- Undecodable originals raise with the file name; RAW is tried as a last resort
"""

import io
import json

import pytest
import requests
from PIL import Image

import immich_client
from image_decode import RAW_SUFFIXES, open_asset, open_preview
from immich_client import ImmichError

BASE = 'http://immich.local'
HEADERS = {'x-api-key': 'k'}


class FakeResponse:
    def __init__(self, status=200, payload=None, chunks=None, content=b''):
        self.status_code = status
        self._payload = payload
        self._chunks = chunks if chunks is not None else [content]
        self.content = content
        self.text = json.dumps(payload) if payload is not None else ''
        self.headers = {'Content-Type': 'image/jpeg'}

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _jpeg_bytes(size=(40, 30)):
    buf = io.BytesIO()
    Image.new('RGB', size, (10, 20, 30)).save(buf, format='JPEG')
    return buf.getvalue()


@pytest.fixture
def calls(monkeypatch):
    """Record every requests.request call; tests queue responses on .responses."""
    recorder = {'calls': [], 'responses': []}

    def fake_request(method, url, **kwargs):
        recorder['calls'].append({'method': method, 'url': url, **kwargs})
        result = recorder['responses'].pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(immich_client.requests, 'request', fake_request)
    return recorder


# ---------------------------------------------------------------------------
# call(): timeouts and transport errors
# ---------------------------------------------------------------------------


def test_call_sets_timeouts_inside_frame_limit(calls):
    calls['responses'].append(FakeResponse(payload=[]))
    immich_client.call('GET', f'{BASE}/api/albums', HEADERS)
    connect, read = calls['calls'][0]['timeout']
    assert connect + read < 50


def test_call_timeout_becomes_504(calls):
    calls['responses'].append(requests.Timeout('slow'))
    with pytest.raises(ImmichError) as exc:
        immich_client.call('GET', f'{BASE}/api/albums', HEADERS)
    assert exc.value.status == 504


def test_call_connection_error_becomes_502(calls):
    calls['responses'].append(requests.ConnectionError('refused'))
    with pytest.raises(ImmichError) as exc:
        immich_client.call('GET', f'{BASE}/api/albums', HEADERS)
    assert exc.value.status == 502


# ---------------------------------------------------------------------------
# resolve_album_id
# ---------------------------------------------------------------------------


def test_resolve_album_id_finds_album(calls):
    calls['responses'].append(FakeResponse(payload=[{'id': 'a1', 'albumName': 'Frame'}]))
    assert immich_client.resolve_album_id(BASE, HEADERS, 'Frame') == 'a1'


def test_resolve_album_id_missing_is_404(calls):
    calls['responses'].append(FakeResponse(payload=[{'id': 'a1', 'albumName': 'Other'}]))
    with pytest.raises(ImmichError) as exc:
        immich_client.resolve_album_id(BASE, HEADERS, 'Frame')
    assert exc.value.status == 404


def test_resolve_album_id_http_error_is_502(calls):
    calls['responses'].append(FakeResponse(status=401, payload={'message': 'nope'}))
    with pytest.raises(ImmichError) as exc:
        immich_client.resolve_album_id(BASE, HEADERS, 'Frame')
    assert exc.value.status == 502
    assert '401' in exc.value.message


# ---------------------------------------------------------------------------
# list_album_assets
# ---------------------------------------------------------------------------


def test_list_album_assets_requests_images_only(calls):
    calls['responses'].append(FakeResponse(payload={'assets': {'items': [{'id': 'x', 'type': 'IMAGE'}]}}))
    immich_client.list_album_assets(BASE, HEADERS, 'a1')
    assert calls['calls'][0]['json']['type'] == 'IMAGE'


def test_list_album_assets_filters_videos_server_ignored(calls):
    items = [{'id': 'img', 'type': 'IMAGE'}, {'id': 'vid', 'type': 'VIDEO'}, {'id': 'untyped'}]
    calls['responses'].append(FakeResponse(payload={'assets': {'items': items}}))
    ids = [a['id'] for a in immich_client.list_album_assets(BASE, HEADERS, 'a1')]
    assert ids == ['img', 'untyped']


def test_list_album_assets_follows_pages(calls):
    calls['responses'].append(FakeResponse(payload={'assets': {'items': [{'id': '1'}], 'nextPage': '2'}}))
    calls['responses'].append(FakeResponse(payload={'assets': {'items': [{'id': '2'}], 'nextPage': None}}))
    ids = [a['id'] for a in immich_client.list_album_assets(BASE, HEADERS, 'a1')]
    assert ids == ['1', '2']
    assert calls['calls'][1]['json']['page'] == 2


def test_list_album_assets_empty_is_404(calls):
    calls['responses'].append(FakeResponse(payload={'assets': {'items': [{'id': 'v', 'type': 'VIDEO'}]}}))
    with pytest.raises(ImmichError) as exc:
        immich_client.list_album_assets(BASE, HEADERS, 'a1')
    assert exc.value.status == 404


# ---------------------------------------------------------------------------
# fetch_original / fetch_preview
# ---------------------------------------------------------------------------


def test_fetch_original_joins_chunks_and_streams(calls):
    calls['responses'].append(FakeResponse(chunks=[b'ab', b'cd']))
    assert immich_client.fetch_original(BASE, HEADERS, 'x') == b'abcd'
    assert calls['calls'][0]['stream'] is True


def test_fetch_original_http_error_is_502(calls):
    calls['responses'].append(FakeResponse(status=404))
    with pytest.raises(ImmichError) as exc:
        immich_client.fetch_original(BASE, HEADERS, 'x')
    assert exc.value.status == 502


def test_fetch_original_deadline_is_504(calls, monkeypatch):
    ticks = iter([0.0, 1.0, immich_client.DOWNLOAD_DEADLINE + 1])
    monkeypatch.setattr(immich_client.time, 'monotonic', lambda: next(ticks))
    calls['responses'].append(FakeResponse(chunks=[b'a', b'b', b'c']))
    with pytest.raises(ImmichError) as exc:
        immich_client.fetch_original(BASE, HEADERS, 'x')
    assert exc.value.status == 504


def test_fetch_original_broken_stream_is_502(calls):
    class Broken(FakeResponse):
        def iter_content(self, chunk_size=1):
            yield b'a'
            raise requests.ConnectionError('reset')

    calls['responses'].append(Broken())
    with pytest.raises(ImmichError) as exc:
        immich_client.fetch_original(BASE, HEADERS, 'x')
    assert exc.value.status == 502


def test_fetch_preview_asks_for_preview_size(calls):
    calls['responses'].append(FakeResponse(content=b'jpeg'))
    assert immich_client.fetch_preview(BASE, HEADERS, 'x') == b'jpeg'
    call = calls['calls'][0]
    assert call['url'].endswith('/api/assets/x/thumbnail')
    assert call['params'] == {'size': 'preview'}


# ---------------------------------------------------------------------------
# image_decode
# ---------------------------------------------------------------------------


def test_open_asset_decodes_jpeg_fully():
    image = open_asset(io.BytesIO(_jpeg_bytes()), 'photo.jpg')
    assert image.size == (40, 30)


def test_open_asset_truncated_file_fails_at_open():
    data = _jpeg_bytes((400, 300))
    with pytest.raises(OSError):
        open_asset(io.BytesIO(data[: len(data) // 2]), 'photo.jpg')


def test_open_asset_garbage_names_the_file():
    with pytest.raises(ValueError, match='clip.mp4'):
        open_asset(io.BytesIO(b'not an image at all' * 10), 'clip.mp4')


def test_open_asset_unknown_bytes_try_raw(monkeypatch):
    import image_decode

    sentinel = Image.new('RGB', (2, 2))
    monkeypatch.setattr(image_decode, '_open_raw', lambda data: sentinel)
    assert open_asset(io.BytesIO(b'garbage' * 10), 'IMG_0001.CR3') is sentinel


def test_raw_suffixes_cover_common_cameras():
    for ext in ('.cr3', '.raf', '.orf', '.rw2', '.dng', '.nef', '.arw'):
        assert ext in RAW_SUFFIXES


def test_open_preview_decodes():
    assert open_preview(io.BytesIO(_jpeg_bytes())).size == (40, 30)


# ---------------------------------------------------------------------------
# Overall deadline shared by every call of one /download
# ---------------------------------------------------------------------------


def test_call_clamps_timeouts_to_deadline(calls, monkeypatch):
    monkeypatch.setattr(immich_client.time, 'monotonic', lambda: 100.0)
    calls['responses'].append(FakeResponse(payload=[]))
    immich_client.call('GET', f'{BASE}/api/albums', HEADERS, deadline=103.0)
    connect, read = calls['calls'][0]['timeout']
    assert connect <= 3.0 and read <= 3.0


def test_call_past_deadline_is_504_without_request(calls, monkeypatch):
    monkeypatch.setattr(immich_client.time, 'monotonic', lambda: 100.0)
    with pytest.raises(ImmichError) as exc:
        immich_client.call('GET', f'{BASE}/api/albums', HEADERS, deadline=99.0)
    assert exc.value.status == 504
    assert calls['calls'] == []


def test_fetch_original_respects_shared_deadline(calls, monkeypatch):
    ticks = iter([100.0, 100.0, 100.5, 102.0])
    monkeypatch.setattr(immich_client.time, 'monotonic', lambda: next(ticks))
    calls['responses'].append(FakeResponse(chunks=[b'a', b'b']))
    with pytest.raises(ImmichError) as exc:
        immich_client.fetch_original(BASE, HEADERS, 'x', deadline=101.0)
    assert exc.value.status == 504
