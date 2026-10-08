"""Prepare the next frame in the background so /download answers at once.

Choosing and rendering a photo takes seconds (listing a large Immich album
alone is ~0.6 s per 1000 assets), all of it with the frame awake and its radio
on. FramePrefetcher renders the next frame after each hand-over and serves it
on the following /download.

Rules that keep it correct:
- One choose-and-render at a time (render_lock), whether background or on
  demand, so two threads never pick a photo or touch tracking files at once.
- A frame is cached with the settings key it was rendered under, and served
  only if that key still matches and no invalidate() happened since its
  render started (generation), so a settings change landing mid-render is
  never served even if the key was already updated when the render began.
- A photo is recorded as shown (RenderedFrame.commit) only when served, so a
  discarded pre-render does not skip it.
- A /download that waited on a background render which failed reports that
  failure instead of asking the device to retry, so a source that keeps
  failing ends in an error rather than a 202 on every retry.
"""

import threading
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RenderedFrame:
    data: bytes
    name: str  # identifies the photo, used in the download file name
    commit: Callable[[], None]  # record the photo as shown


class BusyError(Exception):
    """A background render holds the frame; the caller should ask the device to retry."""


class FramePrefetcher:
    def __init__(self, render, settings_key):
        """render() -> RenderedFrame (raises on failure); settings_key() -> comparable value."""
        self._render = render
        self._settings_key = settings_key
        self._render_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._cached = None  # (settings key, RenderedFrame)
        self._generation = 0  # bumped by invalidate(); a render from an older one is discarded
        self._failure = None  # error of the last background render; read and written under render_lock
        self._thread = None
        self._rerun = False
        self._enabled = False

    def start(self):
        """Enable background rendering and warm the cache."""
        with self._state_lock:
            self._enabled = True
        self.trigger()

    def trigger(self):
        """Prepare the next frame in the background unless one is ready or being made."""
        with self._state_lock:
            if not self._enabled:
                return
            if self._thread is not None:
                # Running: make it look again once done, so a change made
                # during its render is not lost.
                self._rerun = True
                return
            thread = threading.Thread(target=self._work, name='frame-prefetch', daemon=True)
            self._thread = thread
        try:
            thread.start()
        except RuntimeError as error:
            print(f'[prefetch] WARN: could not start the background thread: {error}')
            with self._state_lock:
                self._thread = None

    def invalidate(self):
        """Drop the prepared frame (settings changed) and prepare a new one."""
        with self._state_lock:
            self._cached = None
            self._generation += 1
        self.trigger()

    def take(self, wait):
        """The frame to serve now, recorded as shown.

        Serves the prepared frame if it is still valid, otherwise renders on
        demand. If a background render is running, waits up to `wait` seconds
        for it; raises BusyError if it does not finish in time or its frame went
        stale, so the device retries with a fresh request timeout instead of
        this request also paying for an on-demand render. If the awaited render
        failed, its error is raised instead.
        """
        waited = False
        if not self._render_lock.acquire(blocking=False):
            waited = True
            if not self._render_lock.acquire(timeout=wait):
                raise BusyError()
        try:
            failure, self._failure = self._failure, None
            frame = self._pop_valid()
            if frame is None:
                if waited and failure is not None:
                    # Retrying would only wait on the next attempt and fail again
                    raise failure
                if waited:
                    raise BusyError()
                frame = self._render()
            frame.commit()
        except BusyError:
            # The awaited render went stale: start another for the retry
            self._render_lock.release()
            self.trigger()
            raise
        except BaseException:
            self._render_lock.release()
            raise
        self._render_lock.release()
        self.trigger()
        return frame

    def join(self, timeout=None):
        """Wait for the background thread to finish (for tests and shutdown)."""
        with self._state_lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _pop_valid(self):
        with self._state_lock:
            cached, self._cached = self._cached, None
        if cached is not None and cached[0] == self._settings_key():
            return cached[1]
        return None

    def _has_valid_cache(self):
        with self._state_lock:
            cached = self._cached
        return cached is not None and cached[0] == self._settings_key()

    def _work(self):
        try:
            while True:
                with self._state_lock:
                    self._rerun = False
                with self._render_lock:
                    self._failure = None
                    try:
                        if not self._has_valid_cache():
                            self._render_into_cache()
                    except Exception as error:  # noqa: BLE001 — a background thread must not die silently
                        # Kept under render_lock so a take() waiting on this render sees it.
                        # No retry: the next hand-over or settings change tries again.
                        self._failure = error
                        print(f'[prefetch] WARN: preparing the next frame failed: {error}')
                with self._state_lock:
                    if not self._rerun:
                        # Cleared in the same critical section as the rerun check, or a
                        # trigger() landing in between would see a live thread and be lost.
                        self._thread = None
                        return
        finally:
            # Always clear the handle, or every later trigger() would think a
            # thread is still running and background rendering would stop for good.
            # Only our own: trigger() may already have started a successor.
            with self._state_lock:
                if self._thread is threading.current_thread():
                    self._thread = None

    def _render_into_cache(self):
        with self._state_lock:
            generation = self._generation
        key = self._settings_key()
        frame = self._render()
        with self._state_lock:
            current = generation == self._generation
        if not current or key != self._settings_key():
            print('[prefetch] Settings changed while rendering; discarding and rendering again')
            with self._state_lock:
                self._rerun = True
            return
        with self._state_lock:
            self._cached = (key, frame)
        print(f'[prefetch] Ready: {frame.name}')
