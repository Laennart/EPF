---
phase: 09-image-prefetch
plan: 01
subsystem: testing
tags: [pytest, tdd, prefetch, threading, flask]

# Dependency graph
requires:
  - phase: 07-geolocation-overlay-from-image-metadata
    provides: test conventions (import app as app_module, monkeypatch, caplog patterns)
provides:
  - 10 RED contract tests (PRE-01..PRE-10) locking pre-fetch behavioral contracts
  - reset_prefetch_state fixture in conftest.py
affects: [09-02, 09-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD RED phase: tests reference not-yet-existing symbols via monkeypatch raising=False"
    - "reset_prefetch_state fixture pattern mirrors mock_geo_cache_dir (import app inside function body)"

key-files:
  created:
    - tests/test_prefetch.py
  modified:
    - tests/conftest.py

key-decisions:
  - "PRE-04 (test_cache_miss_fallback) passes in RED phase because /download currently has no cache check; test remains valid after 09-02 implementation"
  - "monkeypatch raising=False used throughout so fixtures/tests are safe before symbols exist"
  - "_valid_config() helper provides minimal dict with all required update_app_config() keys"

patterns-established:
  - "Pattern 1: reset_prefetch_state fixture resets _prefetch_cache and _prefetch_thread with raising=False"
  - "Pattern 2: tests stub both _process_immich_image_to_bytes and _process_local_image_to_bytes to avoid network I/O"

requirements-completed: [PRE-01, PRE-02, PRE-03, PRE-04, PRE-05, PRE-06, PRE-07, PRE-08, PRE-09, PRE-10]

# Metrics
duration: 10min
completed: 2026-06-02
---

# Phase 9 Plan 01: Image Pre-fetch TDD RED Contract Tests Summary

**10 pytest RED contract tests locking PRE-01..PRE-10 pre-fetch behavioral contracts, plus reset_prefetch_state fixture in conftest.py**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-02T00:00:00Z
- **Completed:** 2026-06-02T00:10:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `reset_prefetch_state` fixture to `tests/conftest.py` with `raising=False` safe for RED phase
- Created `tests/test_prefetch.py` with exactly 10 named test functions (PRE-01..PRE-10)
- 9 of 10 tests fail RED (AttributeError/assertion failures for non-existent symbols); all 39 prior tests continue passing

## Task Commits

Each task was committed atomically:

1. **Task 1: Add reset_prefetch_state fixture to conftest.py** - `2840bc2` (test)
2. **Task 2: Create tests/test_prefetch.py with 10 RED contract tests** - `dbaec80` (test)

_Note: TDD tasks have RED commits only in this plan; GREEN commits land in 09-02/09-03._

## Files Created/Modified

- `tests/conftest.py` - Added `reset_prefetch_state` fixture (17 lines appended, existing fixtures preserved)
- `tests/test_prefetch.py` - 10 RED contract tests covering PRE-01..PRE-10, plus `_valid_config()` helper

## Decisions Made

- PRE-04 (test_cache_miss_fallback) passes vacuously in RED phase because `/download` currently has no cache-check integration — this is correct TDD behavior; the test will continue to pass after 09-02 adds the cache path
- `monkeypatch.setattr(..., raising=False)` used throughout so tests work before symbols exist on `app` module
- `_valid_config()` module-level helper provides all required keys for `update_app_config()` (url, album, rotation, enhanced, contrast, strength, display_mode, image_order, sleep_start/end hour/minute)

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Contract tests are locked; Plans 09-02 and 09-03 implement against these exact function signatures
- `_prefetch_lock`, `_prefetch_cache`, `_prefetch_thread` module-level state defined in 09-02
- `prefetch_next_image`, `_trigger_prefetch`, `_invalidate_prefetch_cache`, `_process_immich_image_to_bytes`, `_process_local_image_to_bytes`, `_current_config_hash` functions defined in 09-02/09-03

---
*Phase: 09-image-prefetch*
*Completed: 2026-06-02*
