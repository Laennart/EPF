# Phase 9: Image Pre-fetch - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-02
**Phase:** 09-image-prefetch
**Areas discussed:** Trigger, Storage, Config-change invalidation, Failure + fallback

---

## Trigger — when to kick off pre-fetch

| Option | Description | Selected |
|--------|-------------|----------|
| Post-download only | Kick off immediately after /download returns | |
| Startup + post-download | Pre-fetch once at server startup, then again after each /download | ✓ |
| Post-download + configurable delay | Trigger after /download with a configurable delay before starting | |

**User's choice:** Startup + post-download
**Notes:** Warms the cache before the first request — useful if the server restarts while the device is sleeping.

---

## Storage — memory vs disk

| Option | Description | Selected |
|--------|-------------|----------|
| In-memory (BytesIO global) | Module-level variable, zero disk I/O, lost on restart | |
| Disk temp file | Write to /tmp, survives Docker restarts, OS cleans on reboot | ✓ |
| You decide | Implementation detail delegated to Claude | |

**User's choice:** Disk temp file
**Follow-up — where and cleanup:**

| Option | Description | Selected |
|--------|-------------|----------|
| System temp dir (/tmp), auto-cleaned | Python tempfile module, OS cleans on reboot | ✓ |
| Project directory | Store alongside photos/ or config/ dirs | |
| You decide | Delegated to Claude | |

**Notes:** Single pre-fetched image stored in /tmp via Python's tempfile module.

---

## Config-change invalidation

| Option | Description | Selected |
|--------|-------------|----------|
| Invalidate on config change | Discard cache and re-trigger pre-fetch when config.yaml updates | ✓ |
| Serve stale, re-render on next cycle | Ignore config changes, one stale image per change | |
| You decide | Delegated to Claude | |

**User's choice:** Invalidate on config change
**Notes:** Hook into existing `update_app_config()` which is already called by the `ConfigFileHandler` watcher.

---

## Failure + fallback behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Silent fallback to on-demand | No cache → /download processes synchronously as today | ✓ |
| Retry pre-fetch + fallback | Background thread retries N times before falling back | |
| You decide | Delegated to Claude | |

**User's choice:** Silent fallback to on-demand
**Notes:** Device sees a delay but no error. Background thread logs failures at WARN level.

---

## Claude's Discretion

- Thread-safety mechanism (Lock, Event)
- Module-level state structure (dataclass vs. individual globals)
- Exact metadata for invalidation (config hash vs. mtime)
- Logging verbosity

## Deferred Ideas

None — discussion stayed within phase scope.
