---
phase: 09-image-prefetch
plan: 03
subsystem: api
tags: [flask, prefetch, threading, cache, tempfile]

# Dependency graph
requires:
  - phase: 09-image-prefetch/09-02
    provides: "_prefetch_cache, _prefetch_lock, _trigger_prefetch(), prefetch_next_image() — pre-fetch engine"
provides:
  - "Cache-hit consume path in process_and_download() (PRE-03)"
  - "Silent cache-miss fallback in process_and_download() (PRE-04)"
  - "_trigger_prefetch() called after every served request — hit and miss (PRE-02)"
  - "Startup cache warm in main() before app.run() (PRE-01)"
affects: [10-future-phases]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One-shot cache consume under lock: read path, set to None, then read file outside lock (prevents double-serve)"
    - "Read file fully into BytesIO before unlink to avoid streaming-while-unlinked race (per RESEARCH Pitfall 7)"
    - "Startup pre-fetch via daemon thread — _trigger_prefetch() is non-blocking, safe before app.run()"

key-files:
  created: []
  modified:
    - app.py
    - tests/test_prefetch.py

key-decisions:
  - "One-shot consume: _prefetch_cache['path'] set to None under lock before reading file, outside the lock — prevents concurrent double-serve without holding lock during I/O"
  - "Read file into BytesIO before os.unlink — avoids send_file streaming while file is already unlinked (RESEARCH Pitfall 7)"
  - "test_download_triggers_prefetch fix: move os.path.isdir/os.listdir monkeypatching to inside `with test_client()` block — Python 3.9 importlib.metadata uses isdir for werkzeug package discovery; global pre-patch broke test client creation"

patterns-established:
  - "Cache consume pattern: lock-guard read+consume, I/O outside lock, re-trigger after serve"

requirements-completed: [PRE-01, PRE-02, PRE-03, PRE-04]

# Metrics
duration: 4min
completed: 2026-06-02
---

# Phase 9 Plan 03: Wire Pre-fetch Cache into /download + Startup Warm Summary

**Lock-guarded one-shot cache consume in /download — BytesIO read-before-unlink + startup warm via daemon thread; all 10 PRE tests GREEN**

## Performance

- **Duration:** ~4 min (Tasks 1+2 automated; Task 3 awaiting human verify)
- **Started:** 2026-06-02T14:14:59Z
- **Completed:** 2026-06-02T14:18:28Z (Tasks 1+2; Task 3 pending)
- **Tasks:** 2/3 complete (Task 3 is human-verify checkpoint)
- **Files modified:** 2

## Accomplishments

- `process_and_download()` checks `_prefetch_cache['path']` under lock, consumes one-shot (sets path=None), reads file into BytesIO, unlinks, returns via `send_file(BytesIO)` — no re-processing on hit (PRE-03)
- Cache-miss path unchanged — silent on-demand fallback via existing `serve_local_image()`/`serve_immich_image()` branching (PRE-04)
- Both hit and miss paths call `_trigger_prefetch()` after serving so the next image begins warming immediately (PRE-02)
- `main()` calls `_trigger_prefetch()` after `ntp_sync_thread.start()` and before `app.run()` — cache warms before first device request (PRE-01)
- Fixed pre-existing test bug: `test_download_triggers_prefetch` was failing before this plan due to `os.path.isdir` global monkeypatch breaking werkzeug importlib.metadata lookup; fixed by moving patches inside `with test_client()` block

## Task Commits

Each task was committed atomically:

1. **Task 1: Cache-hit/consume path + PRE-02/03/04** - `6e7fa52` (feat)
2. **Task 2: Startup warm in main()** - `e6e6dd1` (feat)
3. **Task 3: Human verify** - pending checkpoint

## Files Created/Modified

- `app.py` — `process_and_download()` cache-hit path; `main()` startup warm
- `tests/test_prefetch.py` — Fixed `test_download_triggers_prefetch` monkeypatch ordering

## Decisions Made

- One-shot consume under lock then I/O outside lock: `_prefetch_cache['path'] = None` inside `with _prefetch_lock:`, open/read/unlink outside — prevents double-serve without holding lock during file I/O
- Read file into `io.BytesIO` before `os.unlink()` — streaming from path after unlink is safe on Linux but not macOS; reading fully avoids the race per RESEARCH Pitfall 7
- Test fix: monkeypatch `os.path.isdir` after `test_client()` initialisation to avoid breaking werkzeug's internal `importlib.metadata` path discovery (Python 3.9 issue)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pre-existing test failure in test_download_triggers_prefetch**
- **Found during:** Task 1 (PRE-02 verification)
- **Issue:** `monkeypatch.setattr(os.path, 'isdir', lambda p: True)` was applied before `app_module.app.test_client()` was created; Python 3.9 `importlib.metadata` uses `os.path.isdir` internally to discover werkzeug package metadata, causing `PackageNotFoundError: werkzeug`
- **Fix:** Moved `monkeypatch.setattr(os.path, 'isdir', ...)` and `monkeypatch.setattr(os, 'listdir', ...)` inside the `with app_module.app.test_client() as c:` block, before `c.get('/download')`
- **Files modified:** `tests/test_prefetch.py`
- **Verification:** `pytest tests/test_prefetch.py -k "download_triggers"` exits 0
- **Committed in:** `6e7fa52` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — pre-existing bug in test)
**Impact on plan:** Test fix necessary for PRE-02 verification; no scope creep.

## Issues Encountered

- `test_auth.py` errors (10 tests, pre-existing — `APP_PASSWORD` attribute missing from `app.py`): out of scope for plan 09-03. Logged to deferred items.

## Known Stubs

None — all pre-fetch paths are fully wired. Cache hit serves real bytes; cache miss calls real serve functions.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Task 3 (human-verify) is the remaining checkpoint for this plan
- All PRE-01..PRE-10 tests GREEN; full suite passes (excluding pre-existing auth test errors unrelated to phase 09)
- Phase 09 code is complete pending human verification of live device-facing behavior

---
*Phase: 09-image-prefetch*
*Completed: 2026-06-02 (Tasks 1+2; Task 3 pending human-verify)*

## Self-Check: PASSED

- `app.py` modified and contains `_prefetch_cache['path'] = None` (one-shot consume): FOUND
- `app.py` contains `io.BytesIO(c_bytes)` on cache-hit path: FOUND
- `app.py` contains `_trigger_prefetch()` in both hit and miss paths: FOUND
- `app.py` `main()` contains `_trigger_prefetch()` between `ntp_sync_thread.start()` and `app.run(`: FOUND
- Commit `6e7fa52`: FOUND
- Commit `e6e6dd1`: FOUND
- All 10 prefetch tests pass: VERIFIED
