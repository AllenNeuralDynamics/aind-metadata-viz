# Build Plan: Session Status Viewer (Phase 0)

_March 2026 — Doug Ollerenshaw / Scientific Computing_

---

## Goal

Add a `session_viewer` page to the AIND metadata portal that gives scientists a single view of
where their data collection sessions are in the pipeline. The initial target is the
**Cognitive Flexibility in Patch Foraging** project (VR Foraging + FIP).

This is a **read-only viewer**. It makes zero changes to any existing system.

---

## Background

The full problem statement and phased proposal is in `problem_statement.md`. This document
covers only the Phase 0 implementation scoped to this repository.

Key insight: the DTS already tracks sessions end-to-end (including Code Ocean pipeline runs),
and the metadata portal already shows registered assets. What is missing is a single view that
joins these two sources and surfaces gaps — especially DTS failures that never make it to DocDB.

---

## Architecture

### Two data sources

| Source | Access pattern | Why |
|--------|---------------|-----|
| DocDB (MongoDB) | Server-side Python via `aind-data-access-api` | Accessible from anywhere via `api.allenneuraldynamics.org` |
| DTS REST API (`http://aind-data-transfer-service`) | Server-side Python via `requests` | On-prem hostname; requires AIND network or VPN access from the server |

### Data flow

```
User selects date range → clicks Load Sessions
  ↓
Server queries DTS API (paginated, all job types) → cached 5min
  ↓
Server queries DocDB for project records in the date range → cached 1hr
  ↓
Python joins DTS jobs + DocDB records by session name
  ↓
Table rendered with status indicators and drill-down links
```

### Session name as join key

The DTS `name` field (e.g. `822683_2026-02-26_16-59-38`) is the canonical join key.
DocDB asset names are normalised by `get_session_name()`, which:
- strips processing suffixes (`_processed_`, `_videoprocessed_`, `_sorted_`)
- strips modality prefixes on old-format names (`behavior_`, etc.)

This handles both the new naming convention (`822683_2026-02-26_...`) and the older
convention (`behavior_789919_2025-07-11_...`) that appears in pre-2026 records.

### DTS 14-day limit

The DTS API enforces a hardcoded 14-day lookback window. For sessions older than 14 days:
- DocDB records are still shown (no time limit on DocDB)
- The DTS Status column shows "N/A (>14 days)"
- No DTS drill-down links are available

---

## Scope: Cognitive Flexibility in Patch Foraging only

- DocDB project name: `"Cognitive flexibility in patch foraging"` (exact string, mixed case)
- DTS job type filter (applied in Python after fetching): `{"vr_foraging_fiber", "vr_foraging_v2"}`
- DAG: `transform_and_upload_v2`
- Expected derived modalities: `behavior`, `fib`

Expanding to other projects is straightforward once the pattern is validated.

---

## Table columns

| Column | Source | Link target |
|--------|--------|-------------|
| Subject | parsed from session name | — |
| Session Date | parsed from session name | — |
| DTS Upload | DTS `job_state` | `http://aind-data-transfer-service/job_tasks_table?dag_id=...&dag_run_id=...` |
| Raw Asset | DocDB (`data_level=raw`) | `/view?name=...` on metadata portal |
| Behavior Pipeline | DocDB (`data_level=derived`, behavior modality) | `/view?name=...` |
| FIP Pipeline | DocDB (`data_level=derived`, fib modality) | `/view?name=...` |

Status indicators:
- ✅ complete / registered
- ❌ failed
- ⏳ running / queued
- ⬜ not yet reached / not applicable

What each combination of DTS + DocDB status means:
- DTS ✅ + Raw ✅ + Derived ✅✅ → session fully complete
- DTS ✅ + Raw ✅ + Derived ⬜ → CO pipeline pending or failed (check DTS task view)
- DTS ✅ + Raw ⬜ → upload succeeded but DocDB registration failed (rare)
- DTS ❌ + Raw ⬜ → DTS failure; click DTS cell for task-level breakdown
- DTS ⬜ + Raw ✅ → session > 14 days old, or submitted outside normal DTS flow
- DTS ⬜ + Raw ⬜ → pre-DTS failure (invisible until Phase 2)

---

## Files changed

| File | Change |
|------|--------|
| `src/aind_metadata_viz/utils.py` | Add `TTL_DAY`, `TTL_HOUR`, `CACHE_RESET_DAY`, `CACHE_RESET_HOUR` constants; add `JsonFormatter` class moved from `fiber_viewer.py` |
| `src/aind_metadata_viz/database.py` | Import `CACHE_RESET_DAY`, `CACHE_RESET_HOUR` from utils instead of defining locally |
| `src/aind_metadata_viz/upgrade.py` | Import `TTL_DAY`, `TTL_HOUR` from utils instead of defining locally |
| `src/aind_metadata_viz/fiber_viewer.py` | Import `JsonFormatter` from utils instead of defining locally |
| `src/aind_metadata_viz/session_viewer.py` | **New file** — the session status viewer page |
| `Dockerfile` | Add `session_viewer.py` to `panel serve` command |

---

## Deployment

### Current status: works locally on AIND network / VPN

The DTS query is server-side Python (`requests`). This works whenever the Panel server
process has network access to `http://aind-data-transfer-service`, i.e.:

- Running locally on a machine connected to the AIND VPN ✅
- Running on any on-prem AIND server ✅
- Running on cloud ECS (the normal metadata portal deployment) ❌

### Why cloud ECS doesn't work for DTS

`http://aind-data-transfer-service` is an internal AIND hostname with no route from AWS.
The cloud ECS server can reach DocDB via `api.allenneuraldynamics.org` (internet-accessible
API gateway) but there is no equivalent gateway for the DTS.

### The browser can reach DTS — but CORS blocks JS fetch

When a user on VPN opens the portal in their browser, their browser CAN reach
`http://aind-data-transfer-service` directly. However, a JavaScript `fetch()` call from
`https://metadata-portal.allenneuraldynamics.org` to `http://aind-data-transfer-service`
is blocked by the browser's CORS policy: the DTS API does not send
`Access-Control-Allow-Origin` headers.

Note: `fiber_viewer.py` uses client-side JS to reach `aind-metadata-service` — this works
because the metadata service has CORS headers. DTS does not (yet).

### Path to cloud ECS deployment (one option)

Add CORS middleware to `aind-data-transfer-service`. This is a small change (one line of
Starlette `CORSMiddleware`). With CORS enabled, the app can switch back to a client-side JS
fetch (the `DTSFetcher` ReactiveHTML pattern from `fiber_viewer.py`), which would work from
any browser on VPN regardless of where the server is hosted.

This requires a PR to `aind-data-transfer-service` — it is the only external dependency for
production cloud deployment.

### POC deployment options (no external dependencies)

To share this with Cindy/Bruno for feedback without deploying to cloud ECS:

1. **Run locally and share the URL**: anyone on VPN can hit `http://<your-machine-ip>:5007/session_viewer`
2. **Run on any on-prem AIND server**: `uv run panel serve src/aind_metadata_viz/session_viewer.py --port 5007 --allow-websocket-origin=<hostname>`
3. **Deploy to the dev metadata portal for DocDB-only view**: push to `dev` branch — DTS column will show the error message but all DocDB data renders correctly

---

## What this does NOT do (Phase 0 scope)

- Does not track pre-watchdog events (acquisition start/failure) — Phase 2
- Does not replace the DTS task drill-down or log viewer — just links to them
- Does not add write functionality
- Does not track scheduling, WaterLog, or IACUC metadata
- Does not support projects other than Cognitive Flexibility in Patch Foraging (yet)

---

## Phase 1 / Phase 2 (out of scope here)

- **Phase 1**: Token server — stable session UUID generated at acquisition start, passed through DTS, enabling correlation of pre-DTS events
- **Phase 2**: Rig-side observability — structured logs from acquisition software (using `aind-log-utils`) surface pre-watchdog failures

See `problem_statement.md` for full phased proposal.
