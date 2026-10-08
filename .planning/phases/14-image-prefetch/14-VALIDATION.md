---
phase: 9
slug: image-prefetch
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-02
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (venv at `.venv/`) |
| **Config file** | None detected — tests discovered via default `tests/` directory |
| **Quick run command** | `.venv/bin/pytest tests/test_prefetch.py -x -q` |
| **Full suite command** | `.venv/bin/pytest -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/test_prefetch.py -x -q`
- **After every plan wave:** Run `.venv/bin/pytest -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 0 | PRE-01..PRE-10 | unit | `.venv/bin/pytest tests/test_prefetch.py -x -q` | ❌ W0 | ⬜ pending |
| 09-01-02 | 01 | 1 | PRE-01 | unit | `.venv/bin/pytest tests/test_prefetch.py::test_startup_triggers_prefetch -x` | ❌ W0 | ⬜ pending |
| 09-01-03 | 01 | 1 | PRE-02 | unit | `.venv/bin/pytest tests/test_prefetch.py::test_download_triggers_prefetch -x` | ❌ W0 | ⬜ pending |
| 09-01-04 | 01 | 1 | PRE-03 | unit | `.venv/bin/pytest tests/test_prefetch.py::test_cache_hit_served -x` | ❌ W0 | ⬜ pending |
| 09-01-05 | 01 | 1 | PRE-04 | unit | `.venv/bin/pytest tests/test_prefetch.py::test_cache_miss_fallback -x` | ❌ W0 | ⬜ pending |
| 09-01-06 | 01 | 1 | PRE-05 | unit | `.venv/bin/pytest tests/test_prefetch.py::test_prefetch_failure_logs_warn -x` | ❌ W0 | ⬜ pending |
| 09-01-07 | 01 | 1 | PRE-06 | unit | `.venv/bin/pytest tests/test_prefetch.py::test_config_change_invalidates_cache -x` | ❌ W0 | ⬜ pending |
| 09-01-08 | 01 | 1 | PRE-07 | unit | `.venv/bin/pytest tests/test_prefetch.py::test_no_retry_on_failure -x` | ❌ W0 | ⬜ pending |
| 09-01-09 | 01 | 1 | PRE-08 | unit | `.venv/bin/pytest tests/test_prefetch.py::test_lock_prevents_race -x` | ❌ W0 | ⬜ pending |
| 09-01-10 | 01 | 1 | PRE-09 | unit | `.venv/bin/pytest tests/test_prefetch.py::test_single_thread_guard -x` | ❌ W0 | ⬜ pending |
| 09-01-11 | 01 | 1 | PRE-10 | unit | `.venv/bin/pytest tests/test_prefetch.py::test_temp_file_cleanup -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_prefetch.py` — stubs for PRE-01..PRE-10 (file does not exist; must be created)
- [ ] `tests/conftest.py` — may need `mock_prefetch_cache` fixture; check existing shared fixtures

*Wave 0 creates test stubs before any implementation. All 10 tests must fail RED before implementation begins.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Device receives instant response on cache hit | PRE-03 | Requires physical ESP32 device | Flash firmware, observe `/download` latency on second request |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
