---
phase: 09-image-prefetch
plan: 02
subsystem: api
tags: [threading, prefetch, cache, tempfile, hashlib, refactor]

# Dependency graph
requires:
  - phase: 09-01
    provides: PRE-05..PRE-10 contract tests (RED stubs)
provides:
  - _process_local_image_to_bytes() returning (BytesIO, stem) — pure helper for background thread
  - _process_immich_image_to_bytes() returning (BytesIO, asset_id) — pure helper with single save_downloaded_image call
  - serve_local_image() / serve_immich_image() as thin wrappers preserving identical responses
  - Pre-fetch cache state (_prefetch_lock, _prefetch_cache, _prefetch_thread)
  - prefetch_next_image() daemon worker with WARN logging on failure, no retry
  - _trigger_prefetch() with is_alive guard for single-thread enforcement
  - _invalidate_prefetch_cache() with temp file cleanup
  - _current_config_hash() MD5-based config fingerprint
  - update_app_config() invalidation + re-trigger hook
affects: [09-03]

# Tech tracking
tech-stack:
  added: [hashlib (stdlib), tempfile (stdlib)]
  patterns:
    - Lock-guarded cache dict swap for thread-safe prefetch state updates
    - Background daemon thread with BLE001 exception catch to prevent propagation
    - Pure inner helper functions raising RuntimeError so thread can catch cleanly
    - Config hash via MD5(json.dumps(config, sort_keys=True)) for deterministic invalidation

key-files:
  created: []
  modified:
    - app.py

key-decisions:
  - "_process_immich_image_to_bytes uses RuntimeError raises instead of jsonify returns so background thread can catch exceptions cleanly (Task 1)"
  - "prefetch_next_image assigns local variable asset_id from both _process_local and _process_immich returns — both helpers return (BytesIO, id) tuple (Task 2)"
  - "update_app_config hook placed at end of function body after print() — _invalidate_prefetch_cache and _trigger_prefetch are defined later in file but Python resolves at call time (Task 2)"
  - "_invalidate_prefetch_cache replaces entire dict instead of mutating keys — immutable update pattern (Rule: immutability)"
  - "prefetch_next_image uses global _prefetch_cache to allow full dict replacement under lock (Task 2)"

patterns-established:
  - "Inner processing helpers (_process_*_to_bytes) raise RuntimeError on failure; Flask wrappers catch and return jsonify — clean separation of IO concerns"
  - "Pre-fetch daemon thread: BLE001 noqa for intentional broad except in background worker"

requirements-completed: [PRE-05, PRE-06, PRE-07, PRE-08, PRE-09, PRE-10]

# Metrics
duration: 25min
completed: 2026-06-02
---

# Phase 9 Plan 02: Image Pre-fetch Core Summary

**Extracted pure image-processing helpers from Flask handlers and implemented thread-safe pre-fetch engine with config invalidation, making PRE-05..PRE-10 GREEN**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-02T14:04:56Z
- **Completed:** 2026-06-02T14:30:00Z
- **Tasks:** 2
- **Files modified:** 1 (app.py) + 2 test files copied to worktree

## Accomplishments
- Extracted `_process_local_image_to_bytes()` and `_process_immich_image_to_bytes()` as pure helpers returning `(BytesIO, id)` tuples; `serve_*` functions become thin wrappers with identical HTTP responses
- Implemented `prefetch_next_image()` daemon worker with lock-guarded cache swap, temp file write, and broad exception catch with WARN logging (no retry per D-07)
- Wired `_invalidate_prefetch_cache()` + `_trigger_prefetch()` into `update_app_config()` so every config change voids and rewarms the cache (D-04/D-06)
- PRE-05..PRE-10 all GREEN; 40 existing regression tests (auth/geo/date/overlay) unaffected; ruff clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract _process_*_to_bytes helpers; make serve_* thin wrappers** - `288c068` (refactor)
2. **Task 2: Add pre-fetch cache state, worker thread, config hash, invalidation, update_app_config hook** - `8b343ae` (feat)

## Files Created/Modified
- `app.py` - Added `_process_local_image_to_bytes`, `_process_immich_image_to_bytes`, `_prefetch_lock`, `_prefetch_cache`, `_prefetch_thread`, `_current_config_hash`, `_invalidate_prefetch_cache`, `prefetch_next_image`, `_trigger_prefetch`; refactored `serve_local_image` and `serve_immich_image` as thin wrappers; added `hashlib` and `tempfile` imports; hooked invalidation into `update_app_config`
- `tests/test_prefetch.py` - Copied from main branch to worktree for test execution
- `tests/conftest.py` - Copied from main branch to worktree (includes `reset_prefetch_state` fixture)

## Decisions Made
- `_process_immich_image_to_bytes` raises `RuntimeError` instead of returning jsonify responses — enables background thread to catch failures without Flask context
- `_invalidate_prefetch_cache` replaces the entire `_prefetch_cache` dict under the lock (not per-key mutation) — immutable update pattern
- `prefetch_next_image` uses `global _prefetch_cache` to enable full dict replacement inside lock; uses `BLE001` noqa comment per ruff conventions for intentional broad except
- `_current_config_hash` uses MD5 for non-crypto cache keying (noqa S324 comment added)
- `update_app_config` hook placed after the print statement — functions defined later in file are resolved at call time in Python, so NameError is not possible

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Test execution: `test_prefetch.py` lives in main repo's `tests/` but not in the worktree. Resolved by copying `test_prefetch.py` and `conftest.py` from the main repo into the worktree's `tests/` directory so `import app` resolves to the worktree's modified `app.py`.

## Known Stubs
None - all implementations are complete and functional.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Task 1 (refactor) and Task 2 (pre-fetch engine) are complete
- PRE-05..PRE-10 are GREEN
- PRE-01..PRE-04 (startup warm, `/download` consume path, cache-hit, cache-miss) remain RED — addressed in Plan 09-03
- Plan 09-03 can now implement the `/download` consume path that reads from `_prefetch_cache` and calls `_trigger_prefetch()` for the next image

---
*Phase: 09-image-prefetch*
*Completed: 2026-06-02*
