# Phase 9: Image Pre-fetch - Research

**Researched:** 2026-06-02
**Domain:** Python threading, tempfile, background processing, Flask request lifecycle
**Confidence:** HIGH

## Summary

Phase 9 adds a background pre-fetch mechanism so the ESP32 device always finds a ready-to-serve `.c` file when it calls `/download`. The current synchronous pipeline (select image → download → `scale_img_in_memory()` → `convert_to_c_code_in_memory()`) runs blocking network I/O and CPU-intensive image processing per request. This phase moves that work to a daemon thread, storing the result in a temp file, so `/download` can serve the pre-rendered output instantly.

The implementation fits naturally within the existing codebase. Python's `threading` module is already imported and a daemon thread pattern already exists for NTP sync (line 996). The `tempfile` module (stdlib) handles disk-based temp storage. The entire implementation requires no new dependencies — only new module-level state and two thread functions alongside existing code.

The primary design tension is thread-safety: the background thread writes the cached file path variable at the same time `/download` reads it. A `threading.Lock` protecting the cache state object resolves this. Config invalidation hooks into the existing `update_app_config()` path which is already called on every config change.

**Primary recommendation:** Implement a module-level dataclass (or plain dict) holding `(temp_file_path, asset_id, config_hash)`, guarded by a single `threading.Lock`. Background pre-fetch runs as a daemon thread triggered on startup and after every successful `/download`. Fallback to existing on-demand path when cache is empty.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Pre-fetch triggers on **two events**: (1) server startup — warms cache before first request; (2) after each `/download` is served — immediately kicks off the next image.
- **D-02:** Pre-fetched image stored as **disk temp file** (`/tmp`, via Python's `tempfile` module). Survives Docker container restarts. OS cleans on reboot.
- **D-03:** Store metadata (asset ID, config hash or timestamp) alongside temp file. Single active temp file is sufficient — no pool or queue.
- **D-04:** When `config.yaml` is updated (via `update_app_config()`), **invalidate cached file and trigger a fresh pre-fetch**. `ConfigFileHandler`/`update_app_config()` is the hook point.
- **D-05:** Invalidation also occurs if image selection state changes (e.g., `downloaded_images.json` reset or album change) — planner to determine exact detection strategy.
- **D-06:** If cache is **not ready** when `/download` is called, fall back **silently to on-demand processing** — exactly the current behavior. Background thread logs failures at WARN level.
- **D-07:** No retry logic in the background thread. On failure, cache stays empty; next `/download` triggers another pre-fetch attempt after it completes.

### Claude's Discretion

- Thread-safety mechanism (threading.Lock or threading.Event) for protecting the cached file path variable.
- Whether to track pre-fetch state as a module-level object (e.g., a dataclass or simple dict) or individual globals — consistent with existing module-global pattern.
- Exact metadata stored alongside the temp file for invalidation (config hash vs. config mtime).
- Logging verbosity for pre-fetch start/complete/fail events.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.

</user_constraints>

---

## Standard Stack

### Core (all stdlib — no new dependencies required)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `threading` | stdlib | Daemon background thread | Already imported (line 7); NTP pattern established |
| `tempfile` | stdlib | Named temp file on disk | Safe cross-platform temp file creation with OS cleanup |
| `threading.Lock` | stdlib | Mutual exclusion for cache state | Minimal overhead; no external deps |
| `hashlib` | stdlib | Config hash for invalidation key | Deterministic hash of config dict |
| `json` | stdlib | Serialize config for hashing | Already imported |

### Supporting (already present)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `os` | stdlib | Temp file cleanup (`os.unlink`) | Deleting stale cache on invalidation |
| `io` | stdlib | BytesIO for in-memory pipeline | Already used in `serve_immich_image()` |
| `time` | stdlib | Timestamps for metadata | Already imported |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `threading.Lock` | `threading.Event` | Event signals readiness but doesn't protect state writes; Lock is simpler and sufficient |
| `tempfile.NamedTemporaryFile` | Plain `/tmp/epf_cache.c` hardcoded path | NamedTemporaryFile avoids collisions if multiple instances; but single-instance server, so either works. NamedTemporaryFile with `delete=False` is cleaner |
| Module-level dataclass | Individual module globals | Dataclass groups related state; existing code uses individual globals — plain dict matches existing pattern better |
| Config hash (`hashlib.md5`) | Config mtime | Hash is more reliable — mtime can have sub-second precision issues; hash catches content changes regardless of timing |

**Installation:** No new packages needed. All stdlib.

---

## Architecture Patterns

### Recommended Project Structure

No new files needed. All changes live in `app.py`. New additions:

```
app.py additions:
  _prefetch_cache       # module-level dict: {path, asset_id, config_hash}
  _prefetch_lock        # threading.Lock instance
  _prefetch_config_hash # current config hash for invalidation comparison
  prefetch_next_image() # background thread target function
  _trigger_prefetch()   # helper to spawn/re-spawn thread
  _invalidate_prefetch_cache() # helper called from update_app_config()
```

### Pattern 1: Module-Level Cache State (matches existing globals pattern)

**What:** A plain `dict` (or simple namespace) at module level holds the pre-fetch state. Guarded by a `threading.Lock` on all reads and writes.

**When to use:** Consistent with existing module-level globals (`last_battery_voltage`, `_GEO_CACHE`, `apikey`). No class overhead. Clear and grep-able.

**Example:**
```python
# Module-level state — consistent with existing globals pattern
_prefetch_lock = threading.Lock()
_prefetch_cache = {
    'path': None,       # str path to temp .c file, or None
    'asset_id': None,   # str asset ID stored in cache
    'config_hash': None # str hex digest of config at prefetch time
}
```

### Pattern 2: Daemon Thread (matches existing NTP pattern, app.py:996)

**What:** Background thread registered as daemon in `main()`, so it dies when the main process exits without needing explicit cleanup.

**When to use:** Any long-running background task that should not block server shutdown.

**Example:**
```python
# app.py:996 — existing NTP pattern to follow exactly
ntp_sync_thread = threading.Thread(target=run_daily_ntp_sync, daemon=True)
ntp_sync_thread.start()

# Pre-fetch equivalent (startup warm):
prefetch_thread = threading.Thread(target=prefetch_next_image, daemon=True)
prefetch_thread.start()
```

### Pattern 3: Temp File with delete=False (stdlib tempfile)

**What:** `tempfile.NamedTemporaryFile(delete=False, suffix='.c', mode='w')` creates a uniquely named file. `delete=False` means the file persists after the handle is closed, allowing `/download` to read it later. Manual cleanup via `os.unlink()` on cache invalidation.

**When to use:** When the file must outlive the creating context manager (background thread creates; request handler reads later).

**Example:**
```python
import tempfile
import os

# In prefetch_next_image():
with tempfile.NamedTemporaryFile(delete=False, suffix='.c', mode='wb') as tmp:
    tmp_path = tmp.name
    tmp.write(c_code_bytes)

# Atomically update cache state
with _prefetch_lock:
    old_path = _prefetch_cache['path']
    _prefetch_cache['path'] = tmp_path
    _prefetch_cache['config_hash'] = _current_config_hash()

# Clean up old temp file after releasing lock
if old_path:
    try:
        os.unlink(old_path)
    except OSError:
        pass  # Already gone — not an error
```

### Pattern 4: Config Invalidation via update_app_config() hook

**What:** `update_app_config()` is called every time config changes (line 718). Adding a cache-discard call at the end of that function ensures any config change immediately voids the pre-fetched result and triggers a new pre-fetch.

**When to use:** Whenever cached data depends on configuration values (rotation, album, overlay settings, etc.).

**Example:**
```python
def update_app_config(new_config):
    # ... existing globals update ...
    _invalidate_prefetch_cache()
    _trigger_prefetch()  # start background re-fetch with new config

def _invalidate_prefetch_cache():
    with _prefetch_lock:
        old_path = _prefetch_cache['path']
        _prefetch_cache['path'] = None
        _prefetch_cache['asset_id'] = None
        _prefetch_cache['config_hash'] = None
    if old_path:
        try:
            os.unlink(old_path)
        except OSError:
            pass
```

### Pattern 5: /download Cache-Hit Path

**What:** `process_and_download()` checks cache first; on hit reads the temp file and returns it; on miss falls back to existing on-demand path. After serving (hit or miss), triggers a new pre-fetch.

**Example:**
```python
@app.route('/download', methods=['GET'])
@require_auth
def process_and_download():
    # ... battery header handling (existing) ...

    # Check cache
    with _prefetch_lock:
        cached_path = _prefetch_cache['path']
        _prefetch_cache['path'] = None  # consume: one-shot cache

    if cached_path and os.path.exists(cached_path):
        try:
            response = send_file(cached_path, mimetype='text/plain',
                                 as_attachment=True, download_name='image.c')
            _trigger_prefetch()
            return response
        except OSError:
            pass  # Fall through to on-demand

    # Fallback: on-demand (existing logic)
    try:
        # ... existing local/immich branching ...
        result = serve_local_image() if local_has_images else serve_immich_image()
        _trigger_prefetch()  # kick off next pre-fetch
        return result
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

### Pattern 6: Config Hash for Invalidation (D-03/D-05)

**What:** Hash the entire `current_config` dict to a stable hex string. When pre-fetching, record the hash at fetch time. On `/download`, if current hash differs from cached hash, treat as stale. More reliable than mtime.

**Example:**
```python
import hashlib
import json

def _current_config_hash() -> str:
    """Return a stable MD5 hex digest of current_config."""
    config_bytes = json.dumps(current_config, sort_keys=True).encode('utf-8')
    return hashlib.md5(config_bytes).hexdigest()
```

### Anti-Patterns to Avoid

- **Holding the lock during disk I/O:** Write to temp file FIRST, then acquire lock to update the path pointer. Long I/O under a lock blocks `/download` from reading the cache at all.
- **Mutating `_prefetch_cache` without the lock:** Dict writes in Python are not atomic across threads when combined with read-modify-write patterns.
- **Using `threading.Thread` without `daemon=True`:** Non-daemon threads block server shutdown.
- **Spawning a new thread for every `/download`:** Use a "thread already running" guard (check with `thread.is_alive()`) to avoid thread pile-up during rapid requests.
- **Deleting the temp file before `/download` has finished reading it:** Consume (set `path = None`) under lock, then delete after `send_file` returns. `send_file` with a path streams the file; it is safe to delete after the response is sent.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Unique temp file naming | Custom `/tmp/epf_XXXXXX.c` scheme | `tempfile.NamedTemporaryFile(delete=False)` | Handles race conditions, permissions, cross-platform |
| Config change detection | Poll config mtime in thread loop | Hook into existing `update_app_config()` | Already called on every change by `ConfigFileHandler` |
| Thread-safe variable access | Custom lock classes | `threading.Lock` (stdlib) | Minimal, well-tested, no overhead |
| Background job queue | Custom work queue | Simple daemon thread re-spawn | No queue needed — single-item cache, single trigger |

**Key insight:** The entire implementation is a thin wrapper around stdlib threading + tempfile + existing processing functions. No new algorithms, no new data structures beyond a protected dict.

---

## Common Pitfalls

### Pitfall 1: Thread pile-up on rapid `/download` calls
**What goes wrong:** Each call to `_trigger_prefetch()` spawns a new thread; if the device retries quickly, multiple background threads run simultaneously writing different temp files.
**Why it happens:** `threading.Thread(...).start()` always creates a new thread unless guarded.
**How to avoid:** Keep a module-level reference to the current prefetch thread; check `thread.is_alive()` before spawning. If already running, skip.
**Warning signs:** Multiple `.c` temp files accumulating in `/tmp`.

### Pitfall 2: Lock held during slow network I/O
**What goes wrong:** Lock acquired before `serve_immich_image()` completes; `/download` blocks trying to read `_prefetch_cache['path']`.
**Why it happens:** Lock scope accidentally wraps the entire prefetch pipeline.
**How to avoid:** Only hold lock for the pointer swap (microseconds). All I/O happens outside the lock.

### Pitfall 3: Stale temp file after config change
**What goes wrong:** Config changes album/rotation; pre-fetched image is from old config. `/download` serves wrong image.
**Why it happens:** Cache not invalidated when config changes.
**How to avoid:** `_invalidate_prefetch_cache()` called unconditionally at the end of `update_app_config()`.

### Pitfall 4: Temp file not cleaned up after invalidation
**What goes wrong:** `/tmp` fills up with stale `.c` files (each ~hundreds of KB) over long uptime.
**Why it happens:** `os.unlink()` not called on old path before replacing cache entry.
**How to avoid:** Always capture `old_path` before overwriting cache entry; unlink it outside the lock.

### Pitfall 5: `serve_immich_image()` / `serve_local_image()` return Flask Response objects
**What goes wrong:** These functions return `send_file(...)` responses — not raw bytes — making them unsuitable for direct reuse in background thread.
**Why it happens:** Current functions are designed as request handlers.
**How to avoid:** Extract the `convert_to_c_code_in_memory()` call result (a `BytesIO`) as the cacheable artifact. The background thread needs a refactored inner function that returns `BytesIO` (or writes bytes to disk) rather than a Flask `Response`.
**This is the key refactoring task:** Factor out `_process_image_to_bytes()` (Immich path) and `_process_local_image_to_bytes()` (local path). The existing `serve_*` functions call these and wrap in `send_file`; the background thread calls them directly and writes to disk.

### Pitfall 6: `downloaded_images.json` (tracking file) written twice
**What goes wrong:** Pre-fetch calls `save_downloaded_image(asset_id)` in background, then `/download` also calls it (via `serve_immich_image()`), marking the same image twice OR marking different images.
**Why it happens:** `serve_immich_image()` calls `save_downloaded_image()` internally. If background thread calls this too, the tracking state advances without a real download having occurred.
**How to avoid:** The inner refactored function `_process_immich_image_to_bytes()` must accept a pre-selected `asset_id` (or pre-selected image dict) to avoid double-advancing the tracking. Alternatively: background thread selects AND marks the image; `/download` uses cached result including the already-marked asset ID. This is the intended design per D-03 (store asset_id in metadata).

### Pitfall 7: Flask `send_file` with a path deletes the file before streaming
**What goes wrong:** `os.unlink(cached_path)` called immediately after `send_file(cached_path)` — but `send_file` may still be streaming.
**Why it happens:** Misunderstanding `send_file` — it begins streaming but may not finish before the next line executes.
**How to avoid:** Either (a) read file content into memory before unlinking, or (b) use `send_file` with a `BytesIO` (read content from file, pass BytesIO). Option (b) is cleaner and consistent with how the existing pipeline already uses `BytesIO`.

---

## Code Examples

### Thread-safe cache state initialization
```python
# Source: Python stdlib threading docs — module-level guard pattern
import threading
import tempfile
import hashlib
import json

_prefetch_lock = threading.Lock()
_prefetch_cache = {
    'path': None,
    'asset_id': None,
    'config_hash': None,
}
_prefetch_thread = None  # reference for is_alive() guard
```

### _trigger_prefetch() with is_alive guard
```python
def _trigger_prefetch():
    """Spawn background pre-fetch thread if not already running."""
    global _prefetch_thread
    if _prefetch_thread is not None and _prefetch_thread.is_alive():
        return  # already in progress
    _prefetch_thread = threading.Thread(
        target=prefetch_next_image, daemon=True
    )
    _prefetch_thread.start()
```

### prefetch_next_image() skeleton
```python
def prefetch_next_image():
    """Background worker: process next image and store to temp file.

    On success: updates _prefetch_cache with temp file path.
    On failure: logs WARN, leaves cache empty. No retry (D-07).
    """
    try:
        # Determine source (same branching as process_and_download)
        local_has_images = os.path.isdir(localdir) and any(
            os.path.splitext(f)[1].lower() in ALLOWED_EXTENSIONS
            for f in os.listdir(localdir)
        )
        if local_has_images:
            c_bytes, asset_id = _process_local_image_to_bytes()
        elif apikey:
            c_bytes, asset_id = _process_immich_image_to_bytes()
        else:
            app.logger.warning('[prefetch] No image source configured, skipping.')
            return

        # Write to temp file outside the lock
        with tempfile.NamedTemporaryFile(
            delete=False, suffix='.c', mode='wb'
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(c_bytes)

        # Atomically swap cache entry
        with _prefetch_lock:
            old_path = _prefetch_cache['path']
            _prefetch_cache['path'] = tmp_path
            _prefetch_cache['asset_id'] = asset_id
            _prefetch_cache['config_hash'] = _current_config_hash()

        # Clean up old file outside the lock
        if old_path:
            try:
                os.unlink(old_path)
            except OSError:
                pass

        app.logger.info('[prefetch] Ready: %s (asset=%s)', tmp_path, asset_id)

    except Exception as exc:
        app.logger.warning('[prefetch] Failed to pre-fetch image: %s', exc)
```

### /download cache-hit path
```python
# In process_and_download(), before existing logic:
with _prefetch_lock:
    cached_path = _prefetch_cache.get('path')
    if cached_path:
        _prefetch_cache['path'] = None  # consume

if cached_path and os.path.exists(cached_path):
    try:
        c_bytes = open(cached_path, 'rb').read()
        os.unlink(cached_path)
        _trigger_prefetch()
        return send_file(
            io.BytesIO(c_bytes),
            mimetype='text/plain',
            as_attachment=True,
            download_name='image.c',
        )
    except OSError as exc:
        app.logger.warning('[prefetch] Cache read failed, falling back: %s', exc)

# ... existing on-demand fallback logic ...
```

---

## Runtime State Inventory

> This section is required because Phase 9 modifies how images are selected and what state is written.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `tracking_file` (downloaded_images.json) — records which asset IDs have been served. Pre-fetch advances this list. | Code edit: background thread must mark asset as served at pre-fetch time (not double-mark at `/download`). |
| Live service config | None beyond `config.yaml` on disk. | None — already handled by existing `ConfigFileHandler`. |
| OS-registered state | `/tmp` temp files created by pre-fetch thread. | OS cleans on reboot. Manual `os.unlink()` on invalidation covers in-process cleanup. |
| Secrets/env vars | None new. `IMMICH_API_KEY`, `APP_PASSWORD` unchanged. | None. |
| Build artifacts | None. No new compiled artifacts. | None. |

---

## Validation Architecture

> `workflow.nyquist_validation` key is absent from `.planning/config.json` → treat as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (venv at `.venv/`) |
| Config file | None detected — tests discovered via default `tests/` directory |
| Quick run command | `.venv/bin/pytest tests/test_prefetch.py -x -q` |
| Full suite command | `.venv/bin/pytest -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PRE-01 | Cache is empty at startup; pre-fetch thread starts on `main()` startup | unit | `.venv/bin/pytest tests/test_prefetch.py::test_startup_triggers_prefetch -x` | Wave 0 |
| PRE-02 | After `/download` is served, a new pre-fetch is triggered | unit | `.venv/bin/pytest tests/test_prefetch.py::test_download_triggers_prefetch -x` | Wave 0 |
| PRE-03 | Cache hit: `/download` returns pre-fetched `.c` file instantly (no processing) | unit | `.venv/bin/pytest tests/test_prefetch.py::test_cache_hit_served -x` | Wave 0 |
| PRE-04 | Cache miss (cold): `/download` falls back to on-demand silently | unit | `.venv/bin/pytest tests/test_prefetch.py::test_cache_miss_fallback -x` | Wave 0 |
| PRE-05 | Pre-fetch failure logs WARN, leaves cache empty | unit | `.venv/bin/pytest tests/test_prefetch.py::test_prefetch_failure_logs_warn -x` | Wave 0 |
| PRE-06 | Config change invalidates cache and triggers new pre-fetch | unit | `.venv/bin/pytest tests/test_prefetch.py::test_config_change_invalidates_cache -x` | Wave 0 |
| PRE-07 | No retry on failure (D-07) — cache stays empty until next download | unit | `.venv/bin/pytest tests/test_prefetch.py::test_no_retry_on_failure -x` | Wave 0 |
| PRE-08 | Thread-safety: concurrent cache read/write does not corrupt state | unit | `.venv/bin/pytest tests/test_prefetch.py::test_lock_prevents_race -x` | Wave 0 |
| PRE-09 | Only one pre-fetch thread runs at a time (is_alive guard) | unit | `.venv/bin/pytest tests/test_prefetch.py::test_single_thread_guard -x` | Wave 0 |
| PRE-10 | Temp file deleted on cache invalidation (no `/tmp` leaks) | unit | `.venv/bin/pytest tests/test_prefetch.py::test_temp_file_cleanup -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/test_prefetch.py -x -q`
- **Per wave merge:** `.venv/bin/pytest -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_prefetch.py` — covers PRE-01..PRE-10 (all new; file does not exist)
- [ ] `tests/conftest.py` — may need `mock_prefetch_cache` fixture; existing file covers shared image fixtures

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python `threading` | Background thread | ✓ | stdlib (3.9 venv) | — |
| Python `tempfile` | Disk cache | ✓ | stdlib (3.9 venv) | — |
| Python `hashlib` | Config hash | ✓ | stdlib (3.9 venv) | — |
| `/tmp` writable | Temp file storage | ✓ | macOS + Docker Linux | — |

**Missing dependencies with no fallback:** None.

Step 2.6: No external dependencies beyond stdlib. All required tools confirmed available.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Synchronous processing per request | Pre-fetched and cached before request | Phase 9 | Device sees instant response instead of 2-10s delay |
| `serve_immich_image()` returns Flask Response | Refactored inner `_process_immich_image_to_bytes()` returns bytes | Phase 9 | Background thread can call inner function without Flask context |

**Deprecated/outdated:**
- Nothing in the existing codebase is removed — only augmented. The on-demand fallback path remains fully functional.

---

## Open Questions

1. **D-05: Detection strategy for downloaded_images.json reset**
   - What we know: `reset_tracking_file()` is called inside `serve_immich_image()` when all images in an album have been downloaded (cycle reset). Pre-fetching an image advances the tracking file, but the cache may hold an image selected from the pre-reset list.
   - What's unclear: If a cycle-reset occurs during pre-fetch, should the cache be invalidated? The asset ID stored in cache metadata allows detection: if the asset ID is not in the current `remaining_images` after a reset, the cache is stale.
   - Recommendation: Store `asset_id` in cache metadata (already in D-03). At `/download` cache-hit time, do a lightweight check: if the cached `asset_id` is still in `downloaded_images`, serve it. This is cheap and avoids serving a repeated image. Planner should specify the exact guard.

2. **Refactoring scope for `serve_immich_image()` and `serve_local_image()`**
   - What we know: Both functions return `send_file()` Flask Response objects. The background thread cannot use them directly — it needs bytes.
   - What's unclear: Whether to (a) extract pure inner functions and call them from both the existing route and the background thread, or (b) make the existing functions detect whether they're called from a Flask context and return bytes when not.
   - Recommendation: Option (a) is cleaner and testable. Extract `_process_immich_image_to_bytes() -> (BytesIO, str)` and `_process_local_image_to_bytes() -> (BytesIO, str)`. Existing `serve_*` functions become thin wrappers. This also makes the new code unit-testable without Flask test client.

---

## Project Constraints (from CLAUDE.md)

No CLAUDE.md found at project root. Constraints derive from STATE.md established patterns:

- **Module-level globals:** New pre-fetch state follows module-level globals convention (like `last_battery_voltage`, `_GEO_CACHE`).
- **Daemon threads:** Must use `daemon=True` consistent with NTP thread pattern.
- **Immutable data / no mutation:** Cache state updates create a new dict state under lock rather than mutating in-place — pass new values explicitly.
- **Error handling:** All exceptions in background thread caught; WARN logged; never swallowed silently.
- **No hardcoded values:** Temp file suffix (`.c`) acceptable; no hardcoded paths beyond what `tempfile` generates.
- **Functions < 50 lines:** Extract `_process_*_to_bytes()` helpers to keep functions small.
- **ruff lint:** `target-version = "py39"`, line-length 120. No type annotations required (pyright basic mode).

---

## Sources

### Primary (HIGH confidence)
- Python stdlib `threading` documentation — Lock, Thread, daemon threads — verified via direct code reading of existing app.py patterns
- Python stdlib `tempfile` documentation — `NamedTemporaryFile(delete=False)` usage confirmed via stdlib
- `app.py` direct reading — lines 7, 718, 962-1000, 1018-1164, 662-716

### Secondary (MEDIUM confidence)
- Existing test patterns in `tests/test_auth.py`, `tests/conftest.py` — confirm monkeypatch + module-level attribute pattern for testing

### Tertiary (LOW confidence)
- None identified.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all stdlib, no new deps, confirmed available
- Architecture: HIGH — derived directly from existing code patterns (NTP thread, module globals, ConfigFileHandler)
- Pitfalls: HIGH — derived from careful reading of `serve_immich_image()` / `serve_local_image()` code structure (Flask Response return, tracking file side effects)
- Test requirements: HIGH — follows established TDD RED-first pattern from phases 6, 7, 8

**Research date:** 2026-06-02
**Valid until:** 2026-07-02 (stable stdlib domain; low churn risk)
