# Phase 9: Image Pre-fetch - Context

**Gathered:** 2026-06-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Pre-process the next image in the background on the server so it is immediately ready when the ESP32 device wakes up and calls `/download`. The current per-request processing chain (select image → download from Immich/disk → `scale_img_in_memory()` → `convert_to_c_code_in_memory()`) runs synchronously and causes a delay. This phase moves that work to a background thread, storing the result on disk, so `/download` can return the pre-rendered `.c` file instantly.

**In scope:** Background pre-fetch thread, disk cache for pre-processed `.c` file, cache invalidation on config change, startup pre-warm, fallback to on-demand when cache is cold.

**Out of scope:** Changes to image selection logic, overlay rendering, or device-side behavior.

</domain>

<decisions>
## Implementation Decisions

### Trigger
- **D-01:** Pre-fetch triggers on **two events**: (1) server startup — warms the cache before the first device request; (2) after each `/download` is served — immediately kicks off the next image so the device always finds a ready image when it wakes.

### Storage
- **D-02:** Pre-fetched image is stored as a **disk temp file** (`/tmp`, via Python's `tempfile` module). Disk storage survives Docker container restarts. OS cleans the temp directory on reboot.
- **D-03:** Alongside the temp file, store metadata (asset ID, config hash or timestamp) to support invalidation checks. A single active temp file is sufficient — no pool or queue needed.

### Cache Invalidation
- **D-04:** When `config.yaml` is updated (via the settings UI, which calls `update_app_config()`), **invalidate the cached file and trigger a fresh pre-fetch**. The existing `ConfigFileHandler` / `update_app_config()` is the hook point — add cache discard + re-trigger there.
- **D-05:** Invalidation also occurs if image selection state changes (e.g., `downloaded_images.json` reset or album change) — planner to determine exact detection strategy.

### Fallback
- **D-06:** If the pre-fetched cache is **not ready** when `/download` is called (cold start before first pre-fetch completes, or pre-fetch failed), fall back **silently to on-demand processing** — exactly the current behavior. Device sees a delay but no error. The background thread logs failures at WARN level.
- **D-07:** No retry logic in the background thread. On failure, the cache stays empty; the next `/download` triggers another pre-fetch attempt after it completes.

### Claude's Discretion
- Thread-safety mechanism (threading.Lock or threading.Event) for protecting the cached file path variable.
- Whether to track pre-fetch state as a module-level object (e.g., a dataclass or simple dict) or individual globals — consistent with existing module-global pattern.
- Exact metadata stored alongside the temp file for invalidation (config hash vs. config mtime).
- Logging verbosity for pre-fetch start/complete/fail events.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Core implementation files
- `app.py:7` — `import threading` already present; NTP sync thread at line 996 is the pattern to follow
- `app.py:962-1000` — `run_daily_ntp_sync()` and `threading.Thread(target=..., daemon=True)` startup pattern
- `app.py:1040-1128` — `serve_immich_image()` — the function to extract and call in the background thread
- `app.py:1018-1038` — `serve_local_image()` — also needs pre-fetch support for local photo mode
- `app.py:1129-1164` — `process_and_download()` — the `/download` route; pre-fetch trigger fires after this returns
- `app.py:984-997` — `update_app_config()` call site — hook point for cache invalidation on config change

### Existing background thread pattern
- `app.py:996` — `ntp_sync_thread = threading.Thread(target=run_daily_ntp_sync, daemon=True)` — daemon thread registered in `main()`. Pre-fetch thread should follow the same pattern.

### Config watcher
- `app.py` (search `ConfigFileHandler`) — config file watcher that calls `update_app_config()` on change; this is where D-04 invalidation hooks in.

### Prior phase context
- `.planning/phases/08-auth/08-CONTEXT.md` — D-07: auth is opt-in; similar philosophy applies here (pre-fetch should be a transparent enhancement, not a breaking change)
- `.planning/STATE.md` — Key decisions log; established pattern: module-level globals for env vars and shared state

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `serve_immich_image()` (app.py:1040): Self-contained function that selects + downloads + processes an Immich image. Background thread calls this directly and stores the result to disk instead of returning a Flask response.
- `serve_local_image()` (app.py:1018): Same for local photo mode. Pre-fetch needs to handle both paths (same branching logic as `process_and_download()`).
- `convert_to_c_code_in_memory()`: Returns a BytesIO `.c` file — this is what gets written to the temp file.
- `threading` module already imported; daemon thread pattern established via NTP sync.

### Established Patterns
- Module-level globals for shared state (e.g., `last_battery_voltage`, `apikey`, `_GEO_CACHE`).
- `threading.Thread(target=..., daemon=True)` registered in `main()`.
- Config change propagation via `update_app_config()` — called by `ConfigFileHandler` watcher.

### Integration Points
- `process_and_download()` (`/download`): Post-response, spawn or signal background thread to pre-fetch next image.
- `main()`: Register startup pre-fetch thread alongside existing NTP thread.
- `update_app_config()`: Add cache invalidation call when config changes.

</code_context>

<specifics>
## Specific Ideas

- The background thread should call the same branching logic as `process_and_download()` (local vs. Immich) to ensure the pre-fetched image matches what the real handler would have served.
- The temp file holds the raw `.c` text content; `/download` reads it and returns via `send_file()` with the same mimetype/headers as today.
- A `threading.Lock` or a simple flag variable guards the temp file path so concurrent writes (e.g., rapid config changes) don't corrupt the cache.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 09-image-prefetch*
*Context gathered: 2026-06-02*
