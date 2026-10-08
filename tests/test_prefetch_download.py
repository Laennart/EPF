"""/download wired to the frame prefetcher (Phase 9 integration)."""

import io

import pytest
from PIL import Image

import app as app_module
from prefetch import FramePrefetcher, RenderedFrame


@pytest.fixture
def wired(monkeypatch):
    """A started prefetcher over a fake renderer, swapped in for the app's."""
    state = {'renders': 0, 'committed': [], 'settings': 'v1'}

    def render():
        state['renders'] += 1
        name = f'p{state["renders"]}'
        return RenderedFrame(data=name.encode(), name=name, commit=lambda: state['committed'].append(name))

    prefetcher = FramePrefetcher(render, lambda: state['settings'])
    monkeypatch.setattr(app_module, 'frame_prefetcher', prefetcher)
    monkeypatch.setattr(app_module, 'APP_PASSWORD', '')
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as client:
        state['client'] = client
        state['prefetcher'] = prefetcher
        yield state
    prefetcher.join(timeout=2)


def _bmp(image):
    out = io.BytesIO()
    image.convert('RGB').save(out, format='BMP')
    return out


def test_download_serves_prepared_frame(wired):
    wired['prefetcher'].start()
    wired['prefetcher'].join(timeout=2)
    resp = wired['client'].get('/download')
    assert resp.status_code == 200
    assert resp.data == b'p1'
    assert resp.headers['Content-Type'] == 'application/octet-stream'
    assert 'image_p1.bin' in resp.headers['Content-Disposition']
    assert wired['committed'] == ['p1']


def test_download_prepares_the_next_frame(wired):
    wired['prefetcher'].start()
    wired['prefetcher'].join(timeout=2)
    wired['client'].get('/download')
    wired['prefetcher'].join(timeout=2)
    assert wired['renders'] == 2
    assert wired['client'].get('/download').data == b'p2'


def test_busy_returns_202(wired, monkeypatch):
    def busy(wait):
        raise app_module.BusyError()

    monkeypatch.setattr(wired['prefetcher'], 'take', busy)
    assert wired['client'].get('/download').status_code == 202


def test_render_error_status_reaches_frame(monkeypatch):
    monkeypatch.setattr(app_module, 'APP_PASSWORD', '')
    monkeypatch.setattr(app_module, 'image_source', lambda: None)
    monkeypatch.setattr(app_module, 'frame_prefetcher', FramePrefetcher(app_module.render_next_frame, lambda: 0))
    with app_module.app.test_client() as client:
        resp = client.get('/download')
    assert resp.status_code == 500
    assert 'No image source configured' in resp.get_json()['error']


def test_config_change_invalidates_prepared_frame(wired):
    wired['prefetcher'].start()
    wired['prefetcher'].join(timeout=2)
    app_module.update_app_config({'immich': {**app_module.current_config['immich']}})
    wired['prefetcher'].join(timeout=2)
    assert wired['renders'] == 2
    assert wired['client'].get('/download').data == b'p2'
    assert wired['committed'] == ['p2']


def test_settings_key_changes_with_config(monkeypatch):
    before = app_module.render_settings_key()
    monkeypatch.setitem(app_module.current_config, 'immich', {**app_module.current_config['immich'], 'rotation': 90})
    assert app_module.render_settings_key() != before


def test_settings_key_changes_with_source(monkeypatch):
    monkeypatch.setattr(app_module, 'image_source', lambda: 'local')
    local = app_module.render_settings_key()
    monkeypatch.setattr(app_module, 'image_source', lambda: 'immich')
    assert app_module.render_settings_key() != local


def test_prepared_immich_frame_not_recorded_until_served(tmp_path, monkeypatch):
    """A pre-rendered Immich photo that is discarded is not marked as shown."""
    buf = io.BytesIO()
    Image.new('RGB', (40, 30)).save(buf, format='JPEG')
    monkeypatch.setattr(app_module, 'tracking_file', str(tmp_path / 'tracking.txt'))
    monkeypatch.setattr(app_module, 'url', 'http://immich.local')
    monkeypatch.setattr(app_module, 'albumname', 'Frame')
    monkeypatch.setattr(app_module.immich_client, 'resolve_album_id', lambda *a, **k: 'a1')
    monkeypatch.setattr(
        app_module.immich_client,
        'list_album_assets',
        lambda *a, **k: [{'id': 'only', 'originalPath': 'x.jpg', 'exifInfo': {}}],
    )
    monkeypatch.setattr(app_module.immich_client, 'fetch_original', lambda *a, **k: buf.getvalue())
    monkeypatch.setattr(app_module, 'scale_img_in_memory', lambda image, **k: _bmp(image))
    monkeypatch.setattr(app_module, 'convert_to_binary_in_memory', lambda img: io.BytesIO(b'frame'))

    frame = app_module.render_immich_frame()
    assert app_module.load_downloaded_images() == set()
    frame.commit()
    assert app_module.load_downloaded_images() == {'only'}


def test_unreadable_local_photo_is_recorded_so_the_next_wake_moves_on(tmp_path, monkeypatch):
    """A local photo that cannot be opened is marked shown, else it would be picked forever."""
    photos = tmp_path / 'local'
    photos.mkdir()
    Image.new('RGB', (40, 30)).save(photos / 'good.jpg')
    (photos / 'bad.jpg').write_bytes(b'not a jpeg')
    tracking = tmp_path / 'local_tracking.txt'
    tracking.write_text('good.jpg\n')
    monkeypatch.setattr(app_module, 'localdir', str(photos))
    monkeypatch.setattr(app_module, 'local_tracking_file', str(tracking))

    with pytest.raises(Exception):
        app_module.render_local_frame()
    assert 'bad.jpg' in tracking.read_text().split()


def test_immich_photo_failing_to_render_is_recorded(tmp_path, monkeypatch):
    """A decoded Immich photo that fails to scale is marked shown, so 'newest' does not stick on it."""
    buf = io.BytesIO()
    Image.new('RGB', (40, 30)).save(buf, format='JPEG')
    monkeypatch.setattr(app_module, 'tracking_file', str(tmp_path / 'tracking.txt'))
    monkeypatch.setattr(app_module, 'url', 'http://immich.local')
    monkeypatch.setattr(app_module, 'albumname', 'Frame')
    monkeypatch.setattr(app_module.immich_client, 'resolve_album_id', lambda *a, **k: 'a1')
    monkeypatch.setattr(
        app_module.immich_client,
        'list_album_assets',
        lambda *a, **k: [{'id': 'only', 'originalPath': 'x.jpg', 'exifInfo': {}}],
    )
    monkeypatch.setattr(app_module.immich_client, 'fetch_original', lambda *a, **k: buf.getvalue())

    def broken_scale(image, **kwargs):
        raise ValueError('cannot scale')

    monkeypatch.setattr(app_module, 'scale_img_in_memory', broken_scale)

    with pytest.raises(ValueError):
        app_module.render_immich_frame()
    assert app_module.load_downloaded_images() == {'only'}
