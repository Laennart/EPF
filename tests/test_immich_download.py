"""Route-level tests for /download with the Immich source.

- Immich failures reach the frame as their own status (504/502/404), not a generic 500
- An original that cannot be decoded falls back to Immich's preview
- A photo is recorded as shown only once it has actually been decoded
- 'newest' order starts over instead of crashing when every photo has been shown
"""

import io

import pytest
from PIL import Image

import app as app_module
from immich_client import ImmichError

ASSETS = [
    {'id': 'old', 'originalPath': 'old.jpg', 'exifInfo': {'dateTimeOriginal': '2020-01-01T00:00:00'}},
    {'id': 'new', 'originalPath': 'new.jpg', 'exifInfo': {'dateTimeOriginal': '2024-01-01T00:00:00'}},
]


def _jpeg_bytes():
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), (10, 20, 30)).save(buf, format='JPEG')
    return buf.getvalue()


@pytest.fixture
def immich(tmp_path, monkeypatch):
    """Immich-only /download with the network and the heavy pipeline stubbed out."""
    empty_local = tmp_path / 'local'
    empty_local.mkdir()
    monkeypatch.setattr(app_module, 'localdir', str(empty_local))
    monkeypatch.setattr(app_module, 'tracking_file', str(tmp_path / 'tracking.txt'))
    monkeypatch.setattr(app_module, 'apikey', 'k')
    monkeypatch.setattr(app_module, 'url', 'http://immich.local')
    monkeypatch.setattr(app_module, 'albumname', 'Frame')
    monkeypatch.setattr(app_module, 'APP_PASSWORD', '')
    monkeypatch.setitem(app_module.current_config, 'immich', {**app_module.current_config['immich']})

    stub = {
        'album': lambda base, headers, name, **k: 'a1',
        'assets': lambda base, headers, album_id, **k: list(ASSETS),
        'original': lambda base, headers, asset_id, **k: _jpeg_bytes(),
        'preview': lambda base, headers, asset_id, **k: _jpeg_bytes(),
        'decoded': [],
    }
    monkeypatch.setattr(app_module.immich_client, 'resolve_album_id', lambda *a, **k: stub['album'](*a, **k))
    monkeypatch.setattr(app_module.immich_client, 'list_album_assets', lambda *a, **k: stub['assets'](*a, **k))
    monkeypatch.setattr(app_module.immich_client, 'fetch_original', lambda *a, **k: stub['original'](*a, **k))
    monkeypatch.setattr(app_module.immich_client, 'fetch_preview', lambda *a, **k: stub['preview'](*a, **k))

    def fake_scale(image, **kwargs):
        stub['decoded'].append(image.size)
        buf = io.BytesIO()
        image.convert('RGB').save(buf, format='BMP')
        return buf

    monkeypatch.setattr(app_module, 'scale_img_in_memory', fake_scale)
    monkeypatch.setattr(app_module, 'convert_to_binary_in_memory', lambda img: io.BytesIO(b'frame'))

    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as client:
        stub['client'] = client
        yield stub


def _raise(error):
    def fn(*args, **kwargs):
        raise error

    return fn


def test_download_serves_frame(immich):
    resp = immich['client'].get('/download')
    assert resp.status_code == 200
    assert resp.data == b'frame'


@pytest.mark.parametrize(
    'error',
    [ImmichError('slow', 504), ImmichError('down', 502), ImmichError('Album not found', 404)],
)
def test_immich_error_status_reaches_frame(immich, error):
    immich['album'] = _raise(error)
    resp = immich['client'].get('/download')
    assert resp.status_code == error.status
    assert resp.get_json()['error'] == error.message


def test_undecodable_original_falls_back_to_preview(immich):
    immich['original'] = lambda *a, **k: b'not an image' * 10
    resp = immich['client'].get('/download')
    assert resp.status_code == 200
    assert immich['decoded'] == [(40, 30)]


def test_failed_original_and_preview_reports_file(immich):
    immich['original'] = lambda *a, **k: b'not an image' * 10
    immich['preview'] = _raise(ImmichError('no preview', 502))
    resp = immich['client'].get('/download')
    assert resp.status_code == 500
    assert '.jpg' in resp.get_json()['error']


def test_failed_photo_is_not_marked_shown(immich):
    immich['original'] = _raise(ImmichError('slow', 504))
    immich['client'].get('/download')
    assert app_module.load_downloaded_images() == set()


def test_served_photo_is_marked_shown(immich):
    immich['client'].get('/download')
    assert len(app_module.load_downloaded_images()) == 1


def test_newest_order_restarts_when_everything_shown(immich, monkeypatch):
    monkeypatch.setitem(app_module.current_config['immich'], 'image_order', 'newest')
    client = immich['client']
    assert client.get('/download').status_code == 200
    assert client.get('/download').status_code == 200
    # Both photos shown and nothing newer: must start over, not IndexError
    assert client.get('/download').status_code == 200


def test_undecodable_newest_photo_is_skipped_next_time(immich, monkeypatch):
    monkeypatch.setitem(app_module.current_config['immich'], 'image_order', 'newest')
    immich['original'] = lambda base, headers, asset_id, **k: b'junk' * 10 if asset_id == 'new' else _jpeg_bytes()
    immich['preview'] = _raise(ImmichError('no preview', 502))
    client = immich['client']
    assert client.get('/download').status_code == 500
    # The broken newest photo must not be picked again forever
    assert client.get('/download').status_code == 200


def test_immich_calls_share_one_deadline(immich, monkeypatch):
    seen = []
    immich['album'] = lambda base, headers, name, deadline=None: seen.append(deadline) or 'a1'
    immich['assets'] = lambda base, headers, album_id, deadline=None: seen.append(deadline) or list(ASSETS)
    immich['original'] = lambda base, headers, asset_id, deadline=None: seen.append(deadline) or _jpeg_bytes()
    assert immich['client'].get('/download').status_code == 200
    assert len(seen) == 3 and seen[0] is not None and len(set(seen)) == 1


def test_null_exif_date_does_not_crash_newest(immich, monkeypatch):
    monkeypatch.setitem(app_module.current_config['immich'], 'image_order', 'newest')
    immich['assets'] = lambda *a, **k: [
        {'id': 'n', 'originalPath': 'n.jpg', 'exifInfo': {'dateTimeOriginal': None}},
        {'id': 'd', 'originalPath': 'd.jpg', 'exifInfo': {'dateTimeOriginal': '2024-01-01T00:00:00'}},
    ]
    assert immich['client'].get('/download').status_code == 200
