"""Tests for pre-rendering the next frame (Phase 9, prefetch.FramePrefetcher).

PRE-01: Nothing renders until start(); start() warms the cache in the background
PRE-02: After a frame is served, the next one is prepared
PRE-03: Cache hit: take() serves the prepared frame without rendering
PRE-04: Cache miss: take() renders on demand
PRE-05: A failed background render leaves the cache empty and is logged
PRE-06: invalidate() drops the prepared frame and prepares a new one
PRE-07: No retry loop after a failed background render
PRE-08: Only one choose-and-render runs at a time (background vs on demand)
PRE-09: Only one background thread at a time
PRE-10: A frame rendered with settings that changed meanwhile is never served
PRE-11: A photo is recorded as shown only when its frame is served
PRE-12: take() raises BusyError instead of waiting past its limit
"""

import threading
import time

import pytest

from prefetch import BusyError, FramePrefetcher, RenderedFrame


class FakeSource:
    """A render function with controllable settings, failures and blocking."""

    def __init__(self):
        self.settings = 'v1'
        self.renders = []
        self.committed = []
        self.fail = False
        self.gate = None  # threading.Event the render waits on, if set
        self.started = threading.Event()

    def render(self):
        index = len(self.renders)
        self.renders.append(self.settings)
        self.started.set()
        if self.gate is not None:
            self.gate.wait(timeout=2)
        if self.fail:
            raise RuntimeError('render failed')
        name = f'frame{index}'
        return RenderedFrame(data=name.encode(), name=name, commit=lambda: self.committed.append(name))

    def key(self):
        return self.settings


@pytest.fixture
def source():
    return FakeSource()


@pytest.fixture
def prefetcher(source):
    return FramePrefetcher(source.render, source.key)


def _settle(prefetcher):
    prefetcher.join(timeout=2)


def test_no_render_before_start(prefetcher, source):
    """PRE-01: trigger()/invalidate() before start() do nothing (keeps tests and imports quiet)."""
    prefetcher.trigger()
    prefetcher.invalidate()
    _settle(prefetcher)
    assert source.renders == []


def test_start_warms_cache(prefetcher, source):
    """PRE-01/PRE-03: start() prepares a frame that take() then serves without rendering again."""
    prefetcher.start()
    _settle(prefetcher)
    assert source.renders == ['v1']
    frame = prefetcher.take(wait=1)
    assert frame.name == 'frame0'
    assert len(source.renders) == 1 or source.renders[1:] == ['v1']  # only the follow-up prefetch


def test_take_prepares_next(prefetcher, source):
    """PRE-02: serving a frame starts preparing the next one."""
    prefetcher.start()
    _settle(prefetcher)
    prefetcher.take(wait=1)
    _settle(prefetcher)
    assert len(source.renders) == 2
    assert prefetcher.take(wait=1).name == 'frame1'


def test_cache_miss_renders_on_demand(source):
    """PRE-04: with nothing prepared, take() renders itself."""
    prefetcher = FramePrefetcher(source.render, source.key)
    frame = prefetcher.take(wait=1)
    assert frame.name == 'frame0'


def test_on_demand_errors_propagate(source):
    """PRE-04: an on-demand render failure reaches the caller."""
    source.fail = True
    prefetcher = FramePrefetcher(source.render, source.key)
    with pytest.raises(RuntimeError):
        prefetcher.take(wait=1)


def test_background_failure_leaves_cache_empty_and_logs(prefetcher, source, capsys):
    """PRE-05/PRE-07: a failed background render is logged once and not retried."""
    source.fail = True
    prefetcher.start()
    _settle(prefetcher)
    assert source.renders == ['v1']
    assert '[prefetch]' in capsys.readouterr().out
    source.fail = False
    assert prefetcher.take(wait=1).name == 'frame1'  # rendered on demand


def test_invalidate_drops_and_reprepares(prefetcher, source):
    """PRE-06: invalidate() discards the prepared frame and prepares one with the new settings."""
    prefetcher.start()
    _settle(prefetcher)
    source.settings = 'v2'
    prefetcher.invalidate()
    _settle(prefetcher)
    assert source.renders == ['v1', 'v2']
    assert prefetcher.take(wait=1).name == 'frame1'


def test_settings_changed_mid_render_is_not_served(prefetcher, source):
    """PRE-10: a render that started before a settings change is discarded and redone."""
    source.gate = threading.Event()
    prefetcher.start()
    assert source.started.wait(timeout=1)
    source.settings = 'v2'
    prefetcher.invalidate()  # thread busy: must schedule a rerun, not be ignored
    source.gate.set()
    _settle(prefetcher)
    assert source.renders == ['v1', 'v2']
    assert prefetcher.take(wait=1).name == 'frame1'


def test_stale_cache_is_not_served_even_without_invalidate(prefetcher, source):
    """PRE-10: the settings key is checked again when serving."""
    prefetcher.start()
    _settle(prefetcher)
    source.settings = 'v2'
    assert prefetcher.take(wait=1).name == 'frame1'
    assert source.renders[:2] == ['v1', 'v2']


def test_commit_only_when_served(prefetcher, source):
    """PRE-11: preparing a frame does not record it; serving does; a discarded one never is."""
    prefetcher.start()
    _settle(prefetcher)
    assert source.committed == []
    source.settings = 'v2'
    prefetcher.invalidate()
    _settle(prefetcher)
    prefetcher.take(wait=1)
    assert source.committed == ['frame1']


def test_on_demand_waits_for_background_render(prefetcher, source):
    """PRE-08: take() during a background render waits for it and serves its result."""
    source.gate = threading.Event()
    prefetcher.start()
    assert source.started.wait(timeout=1)
    threading.Timer(0.1, source.gate.set).start()
    frame = prefetcher.take(wait=2)
    assert frame.name == 'frame0'
    assert source.renders[0] == 'v1' and len(source.renders) <= 2


def test_busy_when_background_render_outlasts_wait(prefetcher, source):
    """PRE-12: take() raises BusyError rather than waiting past the frame's limit."""
    source.gate = threading.Event()
    prefetcher.start()
    assert source.started.wait(timeout=1)
    started = time.monotonic()
    with pytest.raises(BusyError):
        prefetcher.take(wait=0.1)
    assert time.monotonic() - started < 1
    source.gate.set()


def test_busy_when_waited_render_failed(prefetcher, source):
    """PRE-12: after waiting on a background render that failed, take() asks the frame to come back."""
    source.gate = threading.Event()
    source.fail = True
    prefetcher.start()
    assert source.started.wait(timeout=1)
    threading.Timer(0.1, source.gate.set).start()
    with pytest.raises(BusyError):
        prefetcher.take(wait=2)


def test_single_background_thread(prefetcher, source):
    """PRE-09: repeated triggers while a render runs start no second render in parallel."""
    source.gate = threading.Event()
    prefetcher.start()
    assert source.started.wait(timeout=1)
    for _ in range(5):
        prefetcher.trigger()
    assert source.renders == ['v1']
    source.gate.set()
    _settle(prefetcher)
    # The cache is full after the first render, so the queued triggers do no more work
    assert source.renders == ['v1']


def test_invalidate_mid_render_discards_even_if_key_unchanged(prefetcher, source):
    """PRE-10: invalidate() during a render voids it even when the key already matched at render start
    (update_app_config swaps current_config before the other globals, then invalidates)."""
    source.gate = threading.Event()
    prefetcher.start()
    assert source.started.wait(timeout=1)
    prefetcher.invalidate()
    source.gate.set()
    _settle(prefetcher)
    assert len(source.renders) == 2
    assert prefetcher.take(wait=1).name == 'frame1'


def test_key_failure_does_not_kill_background_thread(source):
    """A raising settings_key must not leave the prefetcher permanently stuck."""
    calls = {'n': 0}

    def flaky_key():
        calls['n'] += 1
        if calls['n'] == 1:
            raise OSError('listdir failed')
        return 'v1'

    prefetcher = FramePrefetcher(source.render, flaky_key)
    prefetcher.start()
    _settle(prefetcher)
    prefetcher.trigger()
    _settle(prefetcher)
    assert source.renders, 'background rendering never recovered'


def test_busy_after_failed_wait_schedules_next_prefetch(prefetcher, source):
    """After a 202 because the awaited render failed, a new background render is started."""
    source.gate = threading.Event()
    source.fail = True
    prefetcher.start()
    assert source.started.wait(timeout=1)
    threading.Timer(0.1, source.gate.set).start()
    with pytest.raises(BusyError):
        prefetcher.take(wait=2)
    source.fail = False
    source.gate = None
    _settle(prefetcher)
    assert len(source.renders) == 2
