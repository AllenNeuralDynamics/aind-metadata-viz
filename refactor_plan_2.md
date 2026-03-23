# AIND Session MCP & Utils — Improvement Plan for Claude Code

## Background

Three repos are involved:

1. **aind-session-utils** — Python library. All data access, caching, session logic, and status classification.
2. **aind-session-mcp** — MCP server. Thin wrapper: tool definitions, string formatting, nothing else.
3. **aind-metadata-viz** (branch `build_proto_session_viewer`) — Panel web dashboard. Pure rendering.

### Architecture Principles

1. **session-utils provides ALL the data.** Both the MCP and the viewer should call session-utils for everything. If the viewer or MCP needs a function that doesn't exist yet, add it to session-utils.
2. **The MCP is a thin wrapper. Zero logic.** Tool definitions, argument parsing, calls to library functions, string formatting of return values.
3. **The viewer is pure rendering.** It takes structured data from session-utils and turns it into HTML/Panel widgets. On-click handlers call session-utils for on-demand data (logs, metadata records).
4. **Existing function signatures don't change.** New work is additive. Optional parameters can be added to existing functions.

---

## Testing Environment

Development and testing will happen **locally on macOS with VPN connected**. This means:

| Data source | Available? | Notes |
|-------------|-----------|-------|
| DocDB API | ✅ Yes | Works over VPN |
| DTS (Airflow) | ✅ Yes | Works over VPN |
| Code Ocean API | ✅ Yes | Requires `CODEOCEAN_DOMAIN` and `CODEOCEAN_API_TOKEN` in `.env` |
| Watchdog logs | ❌ No | Requires `/allen` network mount (on-prem only) |
| Rig manifests | ❌ No | Requires `/allen` network mount (on-prem only) |
| Rig GUI logs | ❌ No | Requires `/allen` network mount (on-prem only) |

**Implications for testing:**

- All verification scripts and benchmarks in this plan use DocDB + Code Ocean, so they will work locally.
- The viewer will load but the Rig Log, Rig Manifest, and Watchdog columns will show ⬜ for all sessions. This is expected and is the existing graceful-degradation behavior — don't try to "fix" it.
- `fetch_and_build_sessions()` will log warnings about unavailable sources. This is fine.
- The `_availability_note()` in the MCP will report watchdog/manifests as unavailable. This is correct.

**Rules for the agent regarding unavailable sources:**

1. **Don't remove or skip watchdog/manifest/rig-log code.** It must continue to work when the code moves back to the institute VM where `/allen` is mounted.
2. **Don't add workarounds for missing `/allen` access.** The existing graceful degradation (empty columns, logged warnings) is the correct behavior.
3. **When reporting benchmark results, note which sources were unavailable.** E.g. "Tested with DocDB + CO; watchdog/manifests unavailable (no /allen mount)."
4. **The viewer verification (Chunk 5) will show empty Rig Log / Rig Manifest / Watchdog columns.** That's expected. Focus on verifying that the DTS, Raw Asset, CO Pipeline Log, Derived Asset, and CO Derived Asset columns render correctly.

---

## Audit: What's Currently in the Wrong Place

### Data logic trapped in the viewer (`session_viewer.py`)

The viewer's docstring says "pure presentation" but `build_session_table()` is ~120 lines of interleaved data logic and HTML rendering. Here's what should be in session-utils:

| Logic | Currently in | Should be in |
|-------|-------------|-------------|
| Pipeline applicability (does this pipeline apply to this session based on `expected_pipelines` vs `raw_modalities`?) | `build_session_table()` | session-utils: new `build_session_rows()` |
| CO pipeline status classification (`is_pending` → `get_cached_run_id()` → age-based ⏳ vs ❌) | `build_session_table()` | session-utils: new `build_session_rows()` |
| Derived asset matching (which derived asset matches which pipeline column?) | `build_session_table()` | session-utils: new `build_session_rows()` |
| Completeness computation | `build_session_table()` calls `check_completeness()` | Already in session-utils (good), but the call should happen in `build_session_rows()` |
| Column name derivation (`_co_log_col()`, `_co_asset_col()`) | viewer + MCP has its own `_capsule_id_for_pipeline()` | session-utils: `config.py` |
| CO asset URL construction (`f"{CO_DOMAIN}/data-assets/{id}/{name}/data"`) | `co_asset_link_cell()` in viewer | session-utils: `codeocean.py` |
| Capsule ID lookup for a pipeline label | MCP's `_capsule_id_for_pipeline()` | session-utils: `config.py` |

### Logic trapped in the MCP (`__main__.py`)

| Logic | Currently in | Should be in |
|-------|-------------|-------------|
| `_capsule_id_for_pipeline()` — capsule ID lookup | MCP | session-utils: `config.py` |
| Serial DocDB regex queries per session in `get_error_summary` | MCP | session-utils: `batch_get_pipeline_logs()` |
| `check_completeness` loop in `find_incomplete_sessions` | MCP | session-utils: already available via `summarize_sessions()` |
| Session name normalization (missing — agent has to strip prefixes) | nowhere | session-utils: apply `get_session_name()` in every function that accepts names |

---

## The Key New Function: `build_session_rows()`

This is the function that both the viewer and the MCP need. It takes `SessionResult` objects (already produced by `fetch_and_build_sessions()`) and returns structured, classified data — no HTML, no formatting.

```python
@dataclass(frozen=True)
class PipelineColumnStatus:
    """Status of one pipeline column for one session."""
    pipeline_label: str
    status: str           # "complete" | "failed" | "pending" | "never_triggered" | "not_applicable"
    derived_asset_name: str   # empty if no derived asset
    derived_docdb_id: str | None
    co_asset_id: str | None
    co_log_url: str | None    # CO output URL, "pending", or None
    co_data_url: str          # direct link to CO data asset, or ""
    run_id: str | None        # CO computation run ID if status == "failed"

@dataclass(frozen=True)
class SessionTableRow:
    """Structured data for one row in a session status table.

    Contains all pre-computed statuses and metadata needed by any consumer
    (viewer, MCP, export). No HTML, no formatting — pure data.
    """
    # Identity
    session_name: str
    subject_id: str
    session_datetime_display: str     # formatted for display (e.g. "2026-03-22 15:27:38")
    display_name: str                 # full asset name
    modalities: tuple[str, ...]

    # Rig-side
    rig_log_path: str | None
    manifest_status: str | None       # "complete" | "pending" | None
    manifest_rig: str
    watchdog_summary: str | None      # e.g. "FRG.3-D" or None if no events
    watchdog_has_error: bool
    watchdog_events: tuple[dict, ...]

    # Upload
    dts_status: str | None            # "success" | "failed" | "running" | etc.
    dts_url: str
    within_14d: bool

    # Raw asset
    raw_asset_name: str | None
    raw_docdb_id: str | None
    raw_co_asset_id: str | None
    raw_co_data_url: str              # direct link to CO raw asset, or ""

    # Overall completeness
    completeness_status: str          # from check_completeness()

    # Per-pipeline statuses (one per derived_columns entry)
    pipeline_statuses: tuple[PipelineColumnStatus, ...]


def build_session_rows(
    sessions: list[SessionResult],
    derived_columns: list[dict],
    no_derived_expected: frozenset[str] = frozenset(),
) -> list[SessionTableRow]:
    """Convert SessionResult objects to structured table rows.

    This is the presentation-ready data layer. It computes all statuses,
    classifies pipeline states, resolves URLs, and returns structured
    dataclass objects. No HTML, no formatting.

    Both the viewer and the MCP use this function:
    - The viewer renders SessionTableRow fields as HTML cells
    - The MCP formats SessionTableRow fields as text strings

    Args:
        sessions:            List of SessionResult objects from fetch_and_build_sessions().
        derived_columns:     Pipeline column configs from the project config.
        no_derived_expected: Modalities never expected to produce derived assets.

    Returns:
        List of SessionTableRow, one per session, ordered to match input.

    Note:
        This function is purely in-memory — no network calls. It uses
        get_cached_run_id() (cache-only) to classify pipeline statuses.
        The CO run cache must already be warm. In normal usage this is
        guaranteed because fetch_and_build_sessions() warms it before
        returning. Do not call build_session_rows() standalone unless
        you know the cache is current.
    """
```

The viewer's `build_session_table()` becomes a thin wrapper:
```python
# In the viewer — pure rendering, no logic:
def build_session_table(rows: list[SessionTableRow], derived_columns) -> pd.DataFrame:
    """Render SessionTableRow objects as an HTML DataFrame for Tabulator."""
    for row in rows:
        html_row = {
            "Subject": row.subject_id,
            "Session Date": row.session_datetime_display,
            ...
            "CO Pipeline Log": render_co_log_cell(row.pipeline_statuses[0]),  # just HTML
        }
```

The MCP's tools become:
```python
# In the MCP — pure formatting, no logic:
rows = build_session_rows(sessions, derived_columns, no_derived_expected)
failed = [r for r in rows if any(p.status == "failed" for p in r.pipeline_statuses)]
return "\n".join(f"  {r.session_name}" for r in failed)
```

---

## Work Chunks

Each chunk is self-contained. After completing each, the agent **stops and waits for review**. The agent **never commits**.

### Chunk 1: Add `build_session_rows()` and supporting dataclasses to session-utils

**Repo:** `aind-session-utils`
**Files to change:** `src/aind_session_utils/session.py`, `src/aind_session_utils/__init__.py`

**What to build:**

1. Add `PipelineColumnStatus` and `SessionTableRow` dataclasses (as above)
2. Add `build_session_rows()` function that:
   - Takes `SessionResult` objects + `derived_columns` config
   - Calls `check_completeness()` per session
   - For each pipeline column, determines applicability (from `expected_pipelines` or `raw_modalities`)
   - For applicable pipelines, finds the matching derived asset
   - For sessions missing derived output: checks the CO run cache via `get_cached_run_id()` to classify as "failed" / "pending" / "never_triggered"
   - Returns `list[SessionTableRow]`

This extracts the data logic from the viewer's `build_session_table()` and the MCP's classification needs into a single shared function.

3. Also add to session-utils:
   - Pipeline column name helper → `src/aind_session_utils/config.py`. Return a NamedTuple (not a positional tuple — callers that unpack in the wrong order produce silent bugs):
     ```python
     class PipelineColumnNames(NamedTuple):
         log_col: str
         asset_col: str
         derived_col: str

     def get_pipeline_column_names(col_config: dict) -> PipelineColumnNames:
         """Return column names for a pipeline config entry."""
     ```
   - CO data asset URL builder → `src/aind_session_utils/sources/codeocean.py`:
     ```python
     def get_co_data_url(asset_id: str | None, asset_name: str) -> str:
         """Build the Code Ocean data-asset browser URL, or empty string."""
     ```
   - Capsule ID resolver → `src/aind_session_utils/config.py`:
     ```python
     def resolve_capsule_id(project_name: str, pipeline_label: str) -> tuple[str | None, str]:
         """Look up capsule ID from project + pipeline label. Returns (id, error)."""
     ```

4. Add a private shared classification helper in `session.py` that **both** `build_session_rows()` (Chunk 1) and `classify_incomplete_sessions()` (Chunk 2) call, so the failure-classification heuristic lives in exactly one place:
   ```python
   def _classify_pipeline_status(
       raw_co_asset_id: str | None,
       capsule_id: str,
       session_acquired_ts: float | None,
   ) -> str:
       """Classify one session+pipeline as failed/pending/never_triggered/unknown.

       Uses get_cached_run_id() (no API call). Relies on the CO run cache having
       been warmed already (by fetch_and_build_sessions or _update_co_run_cache).

       never_triggered: not in cache AND session is older than last_updated watermark
       unknown:         not in cache AND session is newer than watermark (stale cache)
       failed:          run_id in cache (pipeline ran but no derived asset exists)
       """
   ```
   This prevents the two chunks from drifting in their classification logic.

Export everything new from `__init__.py`.

**Verification (run as a script):**

```python
from datetime import datetime, timezone
from aind_session_utils.config import load_project_config, to_viewer_config
from aind_session_utils.session import fetch_and_build_sessions, build_session_rows
from aind_session_utils.store import ParquetSessionStore

cfg = to_viewer_config(load_project_config("Dynamic Foraging"))
store = ParquetSessionStore()
dt_from = datetime(2026, 3, 1, tzinfo=timezone.utc)
dt_to = datetime(2026, 3, 23, 23, 59, 59, tzinfo=timezone.utc)

sessions, status = fetch_and_build_sessions(cfg, dt_from, dt_to, store=store)
rows = build_session_rows(sessions, cfg["derived_columns"], cfg.get("no_derived_expected", frozenset()))

print(f"Total rows: {len(rows)}")
complete = [r for r in rows if r.completeness_status == "complete"]
incomplete = [r for r in rows if r.completeness_status != "complete"]
print(f"Complete: {len(complete)}, Incomplete: {len(incomplete)}")

# Count pipeline statuses across incomplete sessions
from collections import Counter
status_counts = Counter()
for r in incomplete:
    for ps in r.pipeline_statuses:
        if ps.status != "not_applicable":
            status_counts[ps.status] += 1
print(f"Pipeline status breakdown: {dict(status_counts)}")

# List failed sessions
failed = [r for r in rows if any(ps.status == "failed" for ps in r.pipeline_statuses)]
print(f"\nFailed sessions ({len(failed)}):")
for r in failed:
    print(f"  {r.session_name}")
```

**Benchmarks:**
- `build_session_rows()` should be **< 1 second** after `fetch_and_build_sessions()` completes (it's all in-memory classification, no network calls)
- The "failed" count should match the viewer's red ❌ count from the screenshot (~12 for March 2026). Report actual count.
- Every `SessionTableRow` should have a `completeness_status` and `pipeline_statuses` tuple
- **Environment note:** `fetch_and_build_sessions()` will log warnings about unavailable watchdog/manifests. Rig Log, Rig Manifest, and Watchdog fields on `SessionTableRow` will be empty/None. This is expected — focus on the pipeline status classification.

---

### Chunk 2: Add `classify_incomplete_sessions()` (lightweight, no fetch_and_build)

**Repo:** `aind-session-utils`
**Files to change:** `src/aind_session_utils/session.py`, `src/aind_session_utils/__init__.py`

**What to build:**

This is the fast path for the MCP. It uses `summarize_sessions()` (DocDB only, ~3s) plus CO cache lookups to classify incomplete sessions — without calling `fetch_and_build_sessions()`.

```python
@dataclass(frozen=True)
class IncompleteSessionInfo:
    session_name: str
    raw_asset_name: str | None
    category: str  # "failed" | "never_triggered" | "pending" | "no_raw" | "unknown"
    run_id: str | None
    missing_modalities: tuple[str, ...]

def classify_incomplete_sessions(
    project_config: dict,
    date_from: datetime,
    date_to: datetime,
    subject: str = "",
) -> tuple[list[IncompleteSessionInfo], SessionSummary]:
    """Classify incomplete sessions by failure mode — DocDB + CO cache only.

    Much faster than fetch_and_build_sessions + build_session_rows because
    it skips DTS, manifests, watchdog, and detailed session assembly.
    Suitable for MCP tools that just need counts and names.

    Cache update policy (mirrors fetch_and_build_sessions):
      For each pipeline capsule, check whether any incomplete session has a
      raw CO asset UUID that is (a) not in the run cache AND (b) was acquired
      AFTER the cache's last_updated watermark. If yes, call
      _update_co_run_cache() once for that capsule. Sessions not in the cache
      that are OLDER than the watermark are classified as "never_triggered" —
      the pipeline genuinely was never started for them. Sessions not in the
      cache that are NEWER than the watermark (and the cache is still stale
      after the update) are "unknown". This avoids unnecessary API calls: if
      all failing sessions are older than the watermark, no CO call is made.

    Uses _classify_pipeline_status() (the same helper as build_session_rows)
    so classification logic stays in one place.
    """
```

**Verification:**

```python
from datetime import datetime, timezone
from aind_session_utils.config import load_project_config, to_viewer_config
from aind_session_utils.session import classify_incomplete_sessions
import time

cfg = to_viewer_config(load_project_config("Dynamic Foraging"))
dt_from = datetime(2026, 3, 1, tzinfo=timezone.utc)
dt_to = datetime(2026, 3, 23, 23, 59, 59, tzinfo=timezone.utc)

t0 = time.time()
classified, summary = classify_incomplete_sessions(cfg, dt_from, dt_to)
elapsed = time.time() - t0

print(f"Completed in {elapsed:.1f}s")
print(f"Total: {summary.total}, Incomplete: {summary.n_incomplete}")
from collections import Counter
cats = Counter(c.category for c in classified)
print(f"Categories: {dict(cats)}")
```

**Benchmarks:**
- Should complete in **< 10 seconds** (vs ~30s for fetch_and_build_sessions)
- The "failed" count should match Chunk 1's `build_session_rows()` output. Both use `_classify_pipeline_status()` and the same watermark logic, so results should be identical for sessions already in the cache. If there is a discrepancy, investigate and fix before moving on — it means the classification logic has drifted.
- Must NOT call `fetch_and_build_sessions`

---

### Chunk 3: Add `batch_get_pipeline_logs()` and cache warming

**Repo:** `aind-session-utils`
**Files to change:** `src/aind_session_utils/sources/codeocean.py`, `src/aind_session_utils/__init__.py`

**What to build:**

**3a.** Batch log fetcher:

```python
def batch_get_pipeline_logs(
    session_names: list[str],
    capsule_id: str,
    versions: tuple[str, ...] = ("v2",),
    max_workers: int = 10,
    timeout_per_session: int = 30,
) -> dict[str, tuple[str | None, str]]:
    """Batch-fetch pipeline logs for multiple sessions.

    1. Normalizes session names via get_session_name()
    2. Resolves raw asset names via a single batch $in DocDB query
    3. Fetches logs in parallel via ThreadPoolExecutor

    Returns dict mapping session_name → (log_text, error_message).
    """
```

**3b.** Public cache warming (needed to avoid thundering-herd races in batch log fetching):

```python
def warm_pipeline_caches(capsule_ids: list[str]) -> None:
    """Pre-warm CO run caches for pipeline capsules. Safe for background threads.

    Call this before batch_get_pipeline_logs() to ensure all run IDs are
    already in the cache before parallel log fetches begin. Without this,
    multiple threads hitting the same cache miss would each independently
    call list_computations() for the same pipeline — a thundering herd.

    Note: classify_incomplete_sessions() does NOT need this — it handles
    cache freshness internally using the watermark comparison logic.
    """
```

**Verification:**

```python
from aind_session_utils.sources.codeocean import batch_get_pipeline_logs, warm_pipeline_caches
import time

# Warm first
warm_pipeline_caches(["250cf9b5-f438-4d31-9bbb-ba29dab47d56"])

# Then batch fetch — use session names from Chunk 1/2's "failed" list
failed_names = [...]  # fill in from earlier results
t0 = time.time()
results = batch_get_pipeline_logs(
    session_names=failed_names,
    capsule_id="250cf9b5-f438-4d31-9bbb-ba29dab47d56",
    versions=("v1", "v2"),
)
elapsed = time.time() - t0

print(f"Fetched {len(results)} logs in {elapsed:.1f}s")
for sname, (log, err) in results.items():
    status = f"GOT LOG ({len(log)} chars)" if log else f"ERROR: {err}"
    print(f"  {sname}: {status}")
```

**Benchmarks:**
- All "failed" sessions (~12): **< 15 seconds** with parallel fetching
- Passing full asset names (`behavior_...`) should work identically to canonical names
- `warm_pipeline_caches()` second call: **< 0.1s**

---

### Chunk 4: Rewrite MCP as a thin wrapper

**Repo:** `aind-session-mcp`
**Files to change:** `src/aind_session_mcp/__main__.py`

**What to change:**

Strip all logic from the MCP. Every tool becomes: parse args → call session-utils → format result as string.

| Tool | Currently calls | Should call |
|------|----------------|------------|
| `get_session_summary` | `summarize_sessions()` | Same (already good) |
| `find_sessions` | `fetch_and_build_sessions()` | Same + `build_session_rows()` for structured output |
| `find_incomplete_sessions` | `fetch_and_build_sessions()` + completeness loop | `summarize_sessions()` only |
| `get_error_summary` | serial `get_raw_record_by_session()` + `_get_pipeline_log()` loop | `batch_get_pipeline_logs()` |
| `get_pipeline_log` | `get_raw_record_by_session()` + `_get_pipeline_log()` | Same but add `get_session_name()` normalization |
| **NEW: `get_failed_sessions`** | — | `classify_incomplete_sessions()` |
| `get_session_detail` | `get_full_record()` | Same + `get_session_name()` normalization |
| `get_session_qc` | `_get_session_qc()` | Same |
| `get_qc_summary` | `_get_qc_records()` + aggregation loop | Move aggregation to session-utils |
| `refresh_sessions` | `_store.refresh()` | Same |

Remove:
- `_capsule_id_for_pipeline()` → use `resolve_capsule_id()`
- All `from aind_session_utils.sources.*` imports that do work
- The serial loop in `get_error_summary`
- The `fetch_and_build_sessions` call in `find_incomplete_sessions`

Add:
- `get_session_name` normalization at the top of every tool accepting session names
- Background cache warming thread on startup
- Updated `instructions` with recommended workflow

**Verification — same as before (Tests 1-5 from the previous plan version).**

The golden path benchmark:
```
1. get_session_summary(...)  → counts + incomplete list        < 5s
2. get_failed_sessions(...)  → categorized by failure mode     < 10s
3. get_error_summary(...)    → logs for "failed" sessions      < 15s
Total: 3 calls, < 30 seconds
```

---

### Chunk 5: Refactor viewer to use `build_session_rows()`

**Repo:** `aind-metadata-viz` (branch `build_proto_session_viewer`)
**Files to change:** `src/aind_metadata_viz/session_viewer.py`

**What to change:**

The viewer's `build_session_table()` becomes a pure rendering function that takes `SessionTableRow` objects and wraps them in HTML. All the data logic moves out.

**Before (current):**
```python
def build_session_table(sessions, derived_columns, no_derived_expected):
    # 120 lines of interleaved data logic + HTML
    for sr in sessions:
        completeness = check_completeness(sr, no_derived_expected)
        # ... pipeline applicability logic ...
        # ... CO run cache lookup ...
        # ... age-based pending vs failed ...
        row["CO Pipeline Log"] = '<span style="cursor:pointer">❌ view log</span>'
```

**After:**
```python
from aind_session_utils import build_session_rows, SessionTableRow

def build_session_table(rows: list[SessionTableRow], derived_columns) -> pd.DataFrame:
    # ~60 lines of pure HTML rendering
    for row in rows:
        html_row["CO Pipeline Log"] = _render_pipeline_cell(row.pipeline_statuses[0])
        # Just wrapping structured data in HTML — no logic
```

The `_do_load` function changes from:
```python
sessions, base_status = fetch_and_build_sessions(...)
df = build_session_table(sessions, derived_columns, no_derived_expected)
```
to:
```python
sessions, base_status = fetch_and_build_sessions(...)
rows = build_session_rows(sessions, derived_columns, no_derived_expected)
df = build_session_table(rows, derived_columns)
```

**Also remove from viewer:**
- `_co_log_col()` / `_co_asset_col()` → import `get_pipeline_column_names()` from session-utils
- The `CO_DOMAIN` import and URL construction → use `get_co_data_url()` from session-utils
- Note: `sort_record_for_display()` stays in the viewer — it is pure display logic (reorders dict keys for JSON rendering) and has no place in a data access library.

**Verification:** Load the viewer, check all columns render correctly, click ❌ log cells, verify the same ~12 failed sessions show up, verify "Only show sessions missing derived asset" checkbox works.

**Environment note:** Without `/allen` mount, the Rig Log, Rig Manifest, and Watchdog columns will show ⬜ for all sessions. This is expected. Verify those columns still *render* (no errors) — they just won't have data. Full verification of those columns happens when the code moves back to the institute VM.

---

## Summary of New Public API Surface (aind-session-utils)

| Function / Class | Module | Purpose |
|-----------------|--------|---------|
| `SessionTableRow` | session.py | Structured per-session data for table display |
| `PipelineColumnStatus` | session.py | Per-pipeline status for one session |
| `build_session_rows()` | session.py | Convert SessionResults → structured table rows |
| `IncompleteSessionInfo` | session.py | Lightweight classification result |
| `classify_incomplete_sessions()` | session.py | Fast classify (DocDB + CO cache, no full fetch) |
| `_classify_pipeline_status()` | session.py | Private helper shared by build_session_rows and classify_incomplete_sessions |
| `batch_get_pipeline_logs()` | sources/codeocean.py | Parallel log fetching |
| `warm_pipeline_caches()` | sources/codeocean.py | Pre-warm CO caches before batch log fetching (thundering-herd guard) |
| `resolve_capsule_id()` | config.py | Capsule ID from project + pipeline label |
| `PipelineColumnNames` | config.py | NamedTuple: log_col, asset_col, derived_col |
| `get_pipeline_column_names()` | config.py | Column name derivation from config, returns PipelineColumnNames |
| `get_co_data_url()` | sources/codeocean.py | Build CO data asset browser URL |

---

## What NOT to Change

- `fetch_and_build_sessions()` — viewer's main entry point
- `build_sessions()` — core assembler
- `SessionResult` / `DerivedAssetInfo` — frozen dataclasses, don't change fields
- `summarize_sessions()` — already works well
- `check_completeness()` — used everywhere
- `get_pipeline_log()` — viewer calls this on-demand for modal display
- `get_full_record()` — viewer calls this on-demand for JSON inspector
- `get_cached_run_id()` — still used internally by `build_session_rows()`

---

## Work Order

| Chunk | Repo | Est. Time | Dependency | Key Deliverable |
|-------|------|-----------|------------|----------------|
| 1 | session-utils | 3 hr | None | `build_session_rows()`, `SessionTableRow`, helpers |
| 2 | session-utils | 2 hr | None | `classify_incomplete_sessions()` |
| 3 | session-utils | 1.5 hr | None | `batch_get_pipeline_logs()`, cache persistence |
| 4 | session-mcp | 2 hr | Chunks 1-3 | Thin wrapper rewrite |
| 5 | metadata-viz | 1.5 hr | Chunk 1 | Viewer refactor to use `build_session_rows()` |

**Total: ~10 hours of agent work + human review between chunks.**

---

## Rules for the Agent

1. **Never commit.** Make changes locally. Report what changed and test results.
2. **One chunk at a time.** Complete a chunk, run verification, report results, stop.
3. **Don't modify existing function signatures.** All new work is additive.
4. **Don't put logic in the MCP or viewer.** If you need a function, put it in session-utils.
5. **Run benchmarks after each chunk.** Report actual times and counts.
6. **The viewer is the ground truth.** If your classification counts don't match what the viewer shows, investigate and explain the discrepancy.
7. **If a benchmark fails, fix it before moving on.**