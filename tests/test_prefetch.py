"""Contract tests for Phase 9: Image Pre-fetch (PRE-01..PRE-10).

These tests MUST fail (RED) until Plans 09-02 and 09-03 land — TDD contract.

PRE-01: Cache is empty at startup; pre-fetch thread starts on _trigger_prefetch()
PRE-02: After /download is served, a new pre-fetch is triggered
PRE-03: Cache hit: /download returns pre-fetched .c file instantly (no processing)
PRE-04: Cache miss (cold): /download falls back to on-demand silently
PRE-05: Pre-fetch failure logs WARN, leaves cache empty
PRE-06: Config change invalidates cache and triggers new pre-fetch
PRE-07: No retry on failure (D-07) — cache stays empty until next download
PRE-08: Thread-safety: concurrent cache read/write does not corrupt state
PRE-09: Only one pre-fetch thread runs at a time (is_alive guard)
PRE-10: Temp file deleted on cache invalidation (no /tmp leaks)
"""

import logging
import os
import tempfile
import threading
import time

import pytest

import app as app_module


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _valid_config():
    """Minimal valid config dict accepted by update_app_config()."""
    return {'immich': {
        'url': 'http://x', 'album': 'a', 'rotation': 0, 'enhanced': False,
        'contrast': 1.0, 'strength': 1.0, 'display_mode': 'fit',
        'image_order': 'random', 'sleep_start_hour': 0, 'sleep_end_hour': 0,
        'sleep_start_minute': 0, 'sleep_end_minute': 0,
    }}


# ---------------------------------------------------------------------------
# PRE-01
# ---------------------------------------------------------------------------

def test_startup_triggers_prefetch(reset_prefetch_state, monkeypatch):
    """PRE-01: _trigger_prefetch() spawns a daemon thread when no thread is alive."""
    called = []

    def fake_prefetch():
        called.append(1)

    monkeypatch.setattr(app_module, 'prefetch_next_image', fake_prefetch, raising=False)
    monkeypatch.setattr(app_module, '_prefetch_thread', None, raising=False)

    app_module._trigger_prefetch()

    # Give the spawned thread a moment to start
    time.sleep(0.05)
    assert called, "prefetch_next_image was not called — _trigger_prefetch() did not spawn a thread"


# ---------------------------------------------------------------------------
# PRE-02
# ---------------------------------------------------------------------------

def test_download_triggers_prefetch(reset_prefetch_state, monkeypatch):
    """PRE-02: GET /download results in _trigger_prefetch being called exactly once."""
    app_module.app.config['TESTING'] = True
    monkeypatch.setattr(app_module, 'APP_PASSWORD', '', raising=False)

    trigger_calls = []

    def fake_trigger():
        trigger_calls.append(1)

    monkeypatch.setattr(app_module, '_trigger_prefetch', fake_trigger, raising=False)

    # Stub both image-source paths so the route actually returns something
    import io
    fake_bytes = io.BytesIO(b'fake_c_data')

    def fake_serve_local():
        from flask import send_file
        fake_bytes.seek(0)
        return send_file(fake_bytes, mimetype='text/plain', as_attachment=True, download_name='image.c')

    def fake_serve_immich():
        from flask import send_file
        fake_bytes.seek(0)
        return send_file(fake_bytes, mimetype='text/plain', as_attachment=True, download_name='image.c')

    monkeypatch.setattr(app_module, 'serve_local_image', fake_serve_local, raising=False)
    monkeypatch.setattr(app_module, 'serve_immich_image', fake_serve_immich, raising=False)

    # Force the local-images path so the route uses serve_local_image
    monkeypatch.setattr(app_module, 'localdir', '/tmp/__epf_fake_local__', raising=False)
    monkeypatch.setattr(os.path, 'isdir', lambda p: True)
    monkeypatch.setattr(os, 'listdir', lambda p: ['a.jpg'])

    with app_module.app.test_client() as c:
        resp = c.get('/download')

    assert resp.status_code == 200
    assert len(trigger_calls) == 1, f"_trigger_prefetch called {len(trigger_calls)} times, expected 1"


# ---------------------------------------------------------------------------
# PRE-03
# ---------------------------------------------------------------------------

def test_cache_hit_served(reset_prefetch_state, monkeypatch, tmp_path):
    """PRE-03: When _prefetch_cache has a valid path, /download returns that content
    WITHOUT calling _process_immich_image_to_bytes or _process_local_image_to_bytes."""
    app_module.app.config['TESTING'] = True
    monkeypatch.setattr(app_module, 'APP_PASSWORD', '', raising=False)

    # Write a temp file with known content
    cached_file = tmp_path / 'cached.c'
    cached_file.write_bytes(b'CACHED')

    monkeypatch.setattr(
        app_module, '_prefetch_cache',
        {'path': str(cached_file), 'asset_id': 'test-id', 'config_hash': 'abc'},
        raising=False,
    )

    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("_process_immich_image_to_bytes was called on a cache hit")

    def _should_not_be_called_local(*args, **kwargs):
        raise AssertionError("_process_local_image_to_bytes was called on a cache hit")

    monkeypatch.setattr(app_module, '_process_immich_image_to_bytes', _should_not_be_called, raising=False)
    monkeypatch.setattr(app_module, '_process_local_image_to_bytes', _should_not_be_called_local, raising=False)
    monkeypatch.setattr(app_module, '_trigger_prefetch', lambda: None, raising=False)

    with app_module.app.test_client() as c:
        resp = c.get('/download')

    assert resp.status_code == 200
    assert b'CACHED' in resp.data, "Response did not contain cached content"


# ---------------------------------------------------------------------------
# PRE-04
# ---------------------------------------------------------------------------

def test_cache_miss_fallback(reset_prefetch_state, monkeypatch):
    """PRE-04: With _prefetch_cache['path']=None, /download falls back on-demand and returns 200."""
    app_module.app.config['TESTING'] = True
    monkeypatch.setattr(app_module, 'APP_PASSWORD', '', raising=False)

    monkeypatch.setattr(
        app_module, '_prefetch_cache',
        {'path': None, 'asset_id': None, 'config_hash': None},
        raising=False,
    )

    serve_calls = []

    import io

    def fake_serve_local():
        serve_calls.append('local')
        from flask import send_file
        return send_file(io.BytesIO(b'on_demand'), mimetype='text/plain', as_attachment=True, download_name='image.c')

    monkeypatch.setattr(app_module, 'serve_local_image', fake_serve_local, raising=False)
    monkeypatch.setattr(app_module, 'localdir', '/tmp/__epf_fake_local__', raising=False)
    monkeypatch.setattr(os.path, 'isdir', lambda p: True)
    monkeypatch.setattr(os, 'listdir', lambda p: ['a.jpg'])

    with app_module.app.test_client() as c:
        resp = c.get('/download')

    assert resp.status_code == 200
    assert serve_calls, "serve_local_image was never called on cache miss"


# ---------------------------------------------------------------------------
# PRE-05
# ---------------------------------------------------------------------------

def test_prefetch_failure_logs_warn(reset_prefetch_state, monkeypatch, caplog):
    """PRE-05: When _process_immich_image_to_bytes raises, prefetch_next_image() logs
    WARNING and leaves _prefetch_cache['path'] as None."""
    monkeypatch.setattr(app_module, 'apikey', 'fake-key', raising=False)
    monkeypatch.setattr(app_module, 'localdir', '/nonexistent_dir_xyz', raising=False)
    monkeypatch.setattr(os.path, 'isdir', lambda p: False)

    def failing_process():
        raise RuntimeError("Simulated prefetch failure")

    monkeypatch.setattr(app_module, '_process_immich_image_to_bytes', failing_process, raising=False)
    monkeypatch.setattr(app_module, '_process_local_image_to_bytes', failing_process, raising=False)

    with caplog.at_level(logging.WARNING):
        app_module.prefetch_next_image()

    assert app_module._prefetch_cache['path'] is None, "_prefetch_cache['path'] should remain None on failure"
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records, "No WARNING was logged when prefetch_next_image() failed"


# ---------------------------------------------------------------------------
# PRE-06
# ---------------------------------------------------------------------------

def test_config_change_invalidates_cache(reset_prefetch_state, monkeypatch, tmp_path):
    """PRE-06: Calling update_app_config() with a valid config dict sets _prefetch_cache['path'] to None."""
    # Create a real temp file to be "cached"
    cached_file = tmp_path / 'old_cached.c'
    cached_file.write_bytes(b'OLD')

    monkeypatch.setattr(
        app_module, '_prefetch_cache',
        {'path': str(cached_file), 'asset_id': 'old-id', 'config_hash': 'old-hash'},
        raising=False,
    )

    # Suppress the _trigger_prefetch side-effect to keep test focused
    monkeypatch.setattr(app_module, '_trigger_prefetch', lambda: None, raising=False)

    app_module.update_app_config(_valid_config())

    assert app_module._prefetch_cache['path'] is None, (
        "_prefetch_cache['path'] should be None after config change"
    )


# ---------------------------------------------------------------------------
# PRE-07
# ---------------------------------------------------------------------------

def test_no_retry_on_failure(reset_prefetch_state, monkeypatch):
    """PRE-07: prefetch_next_image() calls _process_* exactly once on failure — no retry loop."""
    call_count = []

    def failing_once():
        call_count.append(1)
        raise RuntimeError("first and only call")

    monkeypatch.setattr(app_module, 'apikey', 'fake-key', raising=False)
    monkeypatch.setattr(app_module, 'localdir', '/nonexistent_xyz', raising=False)
    monkeypatch.setattr(os.path, 'isdir', lambda p: False)
    monkeypatch.setattr(app_module, '_process_immich_image_to_bytes', failing_once, raising=False)
    monkeypatch.setattr(app_module, '_process_local_image_to_bytes', failing_once, raising=False)

    app_module.prefetch_next_image()

    assert len(call_count) == 1, f"_process_* was called {len(call_count)} times (expected 1, no retry)"


# ---------------------------------------------------------------------------
# PRE-08
# ---------------------------------------------------------------------------

def test_lock_prevents_race(reset_prefetch_state, monkeypatch):
    """PRE-08: app._prefetch_lock is a threading.Lock and can be acquired/released without error."""
    lock = app_module._prefetch_lock
    assert hasattr(lock, 'acquire'), "_prefetch_lock does not have acquire()"
    assert hasattr(lock, 'release'), "_prefetch_lock does not have release()"

    errors = []

    def writer():
        for _ in range(50):
            try:
                with lock:
                    app_module._prefetch_cache['path'] = 'x'
                    app_module._prefetch_cache['path'] = None
            except Exception as exc:
                errors.append(exc)

    def reader():
        for _ in range(50):
            try:
                with lock:
                    _ = app_module._prefetch_cache.get('path')
            except Exception as exc:
                errors.append(exc)

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=reader)
    t1.start()
    t2.start()
    t1.join(timeout=2)
    t2.join(timeout=2)

    assert not errors, f"Concurrent lock usage raised: {errors}"


# ---------------------------------------------------------------------------
# PRE-09
# ---------------------------------------------------------------------------

def test_single_thread_guard(reset_prefetch_state, monkeypatch):
    """PRE-09: _trigger_prefetch() does NOT spawn a second thread when one is already alive."""
    called = []

    def recording_prefetch():
        time.sleep(0.3)

    monkeypatch.setattr(app_module, 'prefetch_next_image', recording_prefetch, raising=False)

    # Start a live stub thread and assign it to _prefetch_thread
    live_thread = threading.Thread(target=lambda: time.sleep(0.5), daemon=True)
    live_thread.start()
    monkeypatch.setattr(app_module, '_prefetch_thread', live_thread, raising=False)

    # Record thread identity before calling _trigger_prefetch
    thread_before = app_module._prefetch_thread

    monkeypatch.setattr(app_module, 'prefetch_next_image', lambda: called.append(1), raising=False)
    app_module._trigger_prefetch()

    assert not called, (
        "prefetch_next_image was called even though a live thread was already running"
    )
    assert app_module._prefetch_thread is thread_before, (
        "_prefetch_thread identity changed — a new thread was spawned"
    )

    live_thread.join(timeout=1)


# ---------------------------------------------------------------------------
# PRE-10
# ---------------------------------------------------------------------------

def test_temp_file_cleanup(reset_prefetch_state, monkeypatch, tmp_path):
    """PRE-10: _invalidate_prefetch_cache() unlinks the temp file at _prefetch_cache['path']."""
    tmp_file = tmp_path / 'to_be_deleted.c'
    tmp_file.write_bytes(b'DELETE_ME')

    assert tmp_file.exists(), "Precondition: temp file should exist before invalidation"

    monkeypatch.setattr(
        app_module, '_prefetch_cache',
        {'path': str(tmp_file), 'asset_id': 'some-id', 'config_hash': 'h'},
        raising=False,
    )

    app_module._invalidate_prefetch_cache()

    assert not os.path.exists(str(tmp_file)), "Temp file was NOT deleted by _invalidate_prefetch_cache()"
    assert app_module._prefetch_cache['path'] is None, "_prefetch_cache['path'] not cleared after invalidation"
