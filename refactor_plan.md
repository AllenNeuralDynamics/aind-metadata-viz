# aind-session-utils: Implementation Plan for Claude Code

## RULES — READ BEFORE DOING ANYTHING

1. **Work in phases.** Complete Phase 1 fully before starting Phase 2. Stop
   and report after each phase. Wait for human approval before proceeding.
2. **Every phase must end with a working viewer.** If the viewer would break
   at the end of a phase, the phase is not done. Do not proceed.
3. **Do not commit.** The human will commit after verifying each phase. When
   a phase is done, tell the human to test the viewer and commit. Do not run
   `git commit` yourself.
4. **At the end of each phase:**
   a. Run the VERIFY checks listed in that phase's DONE WHEN section.
   b. Report what you did and flag any judgment calls or deviations.
   c. Ask the human to start the Panel viewer and test the frontend.
   d. If the human reports issues, fix only those issues. Do not make
      unrelated changes. Do not move on to the next phase.
   e. Once the human confirms it works, suggest a commit message and ask
      the human to commit. Then stop.
5. **Move code, don't rewrite it.** Source functions should be extracted from
   `session_viewer.py` with minimal changes. Do not refactor logic, rename
   variables, or "improve" code unless this plan explicitly says to.
6. **Do not touch session_viewer.py's presentation logic.** HTML rendering,
   Panel widgets, modal handlers, cell click handlers, URL param sync — all
   stay in session_viewer.py. Only change session_viewer.py's imports and
   remove the functions that moved to the subpackage.
7. **Do not add dependencies** beyond what session_viewer.py already uses
   (plus PyYAML for config loading, and pyarrow/fastparquet for parquet in
   Phase 5). Add new dependencies to `pyproject.toml`, not via pip install.
8. **Use `uv` for all package management.** This project uses `uv`, not pip.
   Run `uv sync` to install, `uv run python -c "..."` to check imports.
   Never run `pip install` directly. Both packages (`aind_metadata_viz` and
   `aind_session_utils`) live under `src/` and are auto-discovered by
   `[tool.setuptools.packages.find] where = ["src"]` — no extra pyproject.toml
   needed for the subpackage.
10. **Do not build the MCP server.** That's a separate future project.
11. **Do not optimize queries.** Move them as-is. Performance work comes later.
12. **If you're unsure whether something should move or stay, leave it in
    session_viewer.py.** It's easier to move something later than to untangle
    a bad extraction.
13. **Do not create tests in this plan.** Testing is a separate task. Focus
    on extraction and structural changes only.

## Context

The file `src/aind_metadata_viz/session_viewer.py` on the
`build_proto_session_viewer` branch of `AllenNeuralDynamics/aind-metadata-viz`
contains ~2000 lines mixing query logic, joining logic, caching, and Panel GUI
code. We are extracting the non-GUI logic into a subpackage that can later
become its own repo.

## Target Structure

```
src/aind_session_utils/
├── __init__.py
├── naming.py
├── session.py
├── completeness.py
├── config.py
├── store.py
├── sources/
│   ├── __init__.py
│   ├── docdb.py
│   ├── dts.py
│   ├── codeocean.py
│   ├── watchdog.py
│   ├── manifests.py
│   └── rig_logs.py
└── project_configs/
    ├── cognitive_flexibility.yml
    └── dynamic_foraging.yml
```

---

## PHASE 1: Extract source modules and naming utilities

**Goal:** Move all data-fetching and name-parsing functions out of
session_viewer.py into the subpackage. session_viewer.py imports them back.
No logic changes. At the end of this phase, session_viewer.py is shorter but
behaves identically — all queries still work, all table columns still render.

### Step 1.1: Create directory structure

Create all directories and empty `__init__.py` files for the structure above.

### Step 1.2: Create `naming.py`

Move these functions **verbatim** from session_viewer.py:

```python
# naming.py — session name parsing and canonicalization

_DERIVED_MARKERS = ("_processed_", "_videoprocessed_", "_sorted_")

def get_session_name(asset_name: str) -> str:
    """Extract canonical session key from any asset name.
    Strips derived suffixes and modality prefixes.
    Input:  'behavior_789919_2025-07-11_19-48-01_processed_2025-...'
    Output: '789919_2025-07-11_19-48-01'
    """

def parse_session_name(session_name: str) -> tuple[str, str]:
    """Return (subject_id, display_datetime) from a session name."""

def session_date(session_name: str) -> datetime | None:
    """Parse session date from session name as UTC datetime, or None."""

def session_datetime(session_name: str) -> datetime | None:
    """Parse full session datetime (date + time), or None."""

def get_modalities(record: dict) -> list[str]:
    """Return lowercased modality abbreviations from a DocDB record.
    Handles both V2 'modalities' and V1 'modality' schema fields.
    """
```

Move them exactly as they exist. Update session_viewer.py to import from
`aind_session_utils.naming`.

### Step 1.3: Create `sources/docdb.py`

Move these functions and their supporting code from session_viewer.py:

```python
# sources/docdb.py — DocDB V1/V2 queries

# Move these module-level items:
# - docdb_client_v1, docdb_client_v2, _DOCDB_CLIENTS setup
# - _DOCDB_BATCH_SIZE, _chunked() helper

def get_project_records(
    project_names: tuple[str, ...],
    versions: tuple[str, ...],
    name_regex: str = "",
) -> list[dict]:
    """Fetch all DocDB records for a project. Cached 1hr via pn.cache (for now)."""

def get_raw_records_by_names(
    names: tuple[str, ...],
    versions: tuple[str, ...],
) -> list[dict]:
    """Fast $in lookup for raw records by exact asset name."""

def get_derived_records_by_input_names(
    input_names: tuple[str, ...],
    versions: tuple[str, ...],
) -> list[dict]:
    """Fetch derived records by input_data_name field."""

def get_full_record(name: str) -> dict | None:
    """Fetch complete DocDB record by name. Tries V2 first, falls back to V1."""

def filter_records_by_date(
    records: list[dict],
    date_from: datetime,
    date_to: datetime,
) -> list[dict]:
    """Filter records by date encoded in asset name."""

def is_available() -> bool:
    """Return True if DocDB API is reachable."""
```

**Note on pn.cache:** For now, keep the `@pn.cache` decorators as-is on the
functions that have them. We will replace these with the persistent store in
Phase 5. Do not remove or change caching behavior in this phase.

### Step 1.4: Create `sources/dts.py`

```python
# sources/dts.py — Data Transfer Service queries

# Move: DTS_BASE_URL, DTS_MAX_LOOKBACK_DAYS, DTS_CACHE_TTL

def get_dts_jobs(
    date_from_iso: str,
    date_to_iso: str,
) -> tuple[list[dict], str | None]:
    """Fetch DTS jobs, paginated. Returns (jobs_list, error_or_None)."""

def is_available() -> bool:
    """Return True if DTS API is reachable."""
```

### Step 1.5: Create `sources/codeocean.py`

```python
# sources/codeocean.py — Code Ocean asset and computation queries

# Move ALL CO-related code:
# - _CO_DOMAIN, _co_client, all caches (_co_url_cache, _co_derived_id_cache,
#   _co_raw_id_cache, _co_computation_status_cache, _co_run_cache,
#   _CO_RUN_CACHE_FILE)
# - _get_co_client(), _load_co_run_cache(), _save_co_run_cache(),
#   _update_co_run_cache(), _get_run_id_for_asset()

def get_co_output_url(asset_name: str) -> str | None:
    """Return CO output log URL for a derived asset. Returns 'pending' if not ready."""

def get_raw_co_asset_id(raw_asset_name: str) -> str | None:
    """Look up CO UUID for a raw asset by exact name."""

def get_co_computation_status(
    raw_asset_co_id: str,
    pipeline_capsule_id: str,
    session_ts: float,
) -> str | None:
    """Check pipeline computation status. Returns 'failed'|'running'|None."""

def is_available() -> bool:
    """Return True if CO API credentials are configured and reachable."""
```

### Step 1.6: Create `sources/watchdog.py`

```python
# sources/watchdog.py — Watchdog log events from eng-logtools

# Move: _WATCHDOG_URL, _WATCHDOG_TTL, _watchdog_cache,
#        _query_watchdog_dstest()

def fetch_watchdog_events(
    date_from: datetime,
    date_to: datetime,
) -> dict[str, list[dict]]:
    """Fetch watchdog events for sessions in date range.
    Returns {session_name: [event_dict, ...]} newest-first.
    """

def is_available() -> bool:
    """Return True if eng-logtools is reachable."""
```

**Note:** This function uses `get_session_name` from naming.py. Update the
import inside watchdog.py to: `from aind_session_utils.naming import get_session_name`

### Step 1.7: Create `sources/manifests.py`

```python
# sources/manifests.py — Rig-side manifest file parsing

# Move: MANIFEST_DIR, _MANIFEST_LINE_RE, AIND_LOGS_DIR

def load_manifest_sessions() -> dict[str, dict]:
    """Parse manifest listing files. Returns {session_name: {rig, status, session_raw}}."""

def is_available() -> bool:
    """Return True if MANIFEST_DIR is accessible."""
```

### Step 1.8: Create `sources/rig_logs.py`

```python
# sources/rig_logs.py — Rig-side session log lookup

# Move: _gui_dir_cache, AIND_LOGS_DIR (if not already in manifests.py — 
#        define in one place and import in the other, or define a shared
#        constants location)

def find_rig_log(rig: str, session_name: str) -> str | None:
    """Find the rig log file path for a session on a given rig, or None.
    This is the function currently named find_gui_log_path(). Rename it.
    """

def is_available() -> bool:
    """Return True if AIND_LOGS_DIR is accessible."""
```

**Rename note:** Rename `find_gui_log_path` → `find_rig_log` during the move.
Update the call site in session_viewer.py accordingly.

### Step 1.9: Create `sources/__init__.py`

Export a convenience list of all source module names for availability checking:

```python
SOURCE_MODULES = {
    'docdb': 'aind_session_utils.sources.docdb',
    'dts': 'aind_session_utils.sources.dts',
    'codeocean': 'aind_session_utils.sources.codeocean',
    'watchdog': 'aind_session_utils.sources.watchdog',
    'manifests': 'aind_session_utils.sources.manifests',
    'rig_logs': 'aind_session_utils.sources.rig_logs',
}
```

### Step 1.10: Update session_viewer.py imports

Replace all moved functions with imports from `aind_session_utils`. Example:

```python
# Old:
# (function defined inline in session_viewer.py)

# New:
from aind_session_utils.naming import (
    get_session_name, parse_session_name, session_date,
    session_datetime, get_modalities,
)
from aind_session_utils.sources.docdb import (
    get_project_records, get_raw_records_by_names,
    get_derived_records_by_input_names, get_full_record,
    filter_records_by_date,
)
from aind_session_utils.sources.dts import get_dts_jobs
from aind_session_utils.sources.codeocean import (
    get_co_output_url, get_raw_co_asset_id,
    get_co_computation_status,
)
from aind_session_utils.sources.watchdog import fetch_watchdog_events
from aind_session_utils.sources.manifests import load_manifest_sessions
from aind_session_utils.sources.rig_logs import find_rig_log
```

Remove the moved function bodies from session_viewer.py. Keep everything else
(build_session_table, all HTML cell functions, all Panel code).

### Step 1.11: Create `__init__.py` public API

```python
"""aind-session-utils: query and join AIND session data across systems."""

from aind_session_utils.naming import (
    get_session_name, parse_session_name, session_date,
    session_datetime, get_modalities,
)
```

(More exports will be added in later phases.)

### DONE WHEN (Phase 1):
- [ ] All source query functions live in `aind_session_utils/sources/`
- [ ] All naming functions live in `aind_session_utils/naming.py`
- [ ] `session_viewer.py` imports everything from the subpackage
- [ ] No function is duplicated (exists in only one place)
- [ ] `session_viewer.py` still contains: `build_session_table`, all `*_cell`
      functions, `sort_record_for_display`, `_log_modal_html`,
      `build_panel_app`, `PROJECT_CONFIG`, and all Panel/HTML code
- [ ] The module `aind_session_utils` has zero dependency on Panel
- [ ] **VERIFY**: `python -c "from aind_session_utils.naming import get_session_name"` works
- [ ] **VERIFY**: `python -c "from aind_session_utils.sources.docdb import get_project_records"` works
- [ ] **VERIFY**: session_viewer.py has no import errors
- [ ] **STOP.** Report what moved where. Flag any judgment calls. Ask the
      human to start the Panel viewer and test that the frontend works.
      If the human reports issues, fix only those issues. Once confirmed
      working, suggest commit message: `refactor: phase 1 — extract sources
      and naming to aind_session_utils`. Wait for human to commit.

---

## PHASE 2: Create project configs and config loader

**Goal:** Replace the `PROJECT_CONFIG` Python dict in session_viewer.py with
YAML files and a loader function in the library. At the end of this phase, the
dropdown still shows the same projects, queries still work the same way, but
the config lives in YAML files that are easy to read and edit.

### Step 2.1: Create YAML config files

Create `aind_session_utils/project_configs/cognitive_flexibility.yml`:

```yaml
name: "Cognitive flexibility in patch foraging"

query:
  docdb_project_names:
    - "Cognitive flexibility in patch foraging"
  docdb_versions: ["v2"]
  dts_job_types:
    - vr_foraging_fiber
    - vr_foraging_v2

expectations:
  no_derived_expected:
    - behavior-videos
  pipelines:
    - label: "Behavior"
      modalities: [behavior]
      co_capsule_id: "da8785b1-1597-41c6-af30-5844f52d4947"
    - label: "Fiber Photometry"
      modalities: [fib, fiber]
      co_capsule_id: "9f8af19f-d107-488d-a3c1-a1f9db29401f"
```

Create `aind_session_utils/project_configs/dynamic_foraging.yml`:

```yaml
name: "Dynamic Foraging"

query:
  docdb_name_regex: "^behavior_"
  docdb_versions: ["v1", "v2"]
  dts_job_types:
    - dynamic_foraging_behavior_and_fiber
    - dynamic_foraging_behavior_only
    - dynamic_foraging_compression
    - dynamic_foraging
  use_manifests: true

expectations:
  no_derived_expected:
    - behavior-videos
  pipelines:
    - label: "Dynamic Foraging Pipeline"
      modalities: [behavior, fib, fiber, behavior-videos]
      co_capsule_id: "250cf9b5-f438-4d31-9bbb-ba29dab47d56"
```

### Step 2.2: Create `config.py`

```python
# config.py — project config loader

import os
import yaml
from pathlib import Path

_BUNDLED_CONFIG_DIR = Path(__file__).parent / "project_configs"

def load_project_config(
    project_name: str,
    user_config_dir: str | Path | None = None,
) -> dict | None:
    """
    Load a project config by name.

    Checks user_config_dir first (if provided), then bundled defaults.
    Returns the parsed YAML as a dict, or None if not found.

    Args:
        project_name: The display name of the project (matched against
            the 'name' field in YAML files).
        user_config_dir: Optional path to a directory of user-provided
            YAML config files that override or extend bundled configs.
    """

def list_project_configs(
    user_config_dir: str | Path | None = None,
) -> list[dict]:
    """
    Return all available project configs (user overrides + bundled).

    Each entry is the full parsed config dict. User configs with the
    same 'name' as a bundled config take precedence.
    """

def get_project_query_config(config: dict) -> dict:
    """
    Extract the 'query' section from a project config.

    Returns dict with keys: docdb_project_names, docdb_versions,
    docdb_name_regex, dts_job_types, use_manifests. Missing keys
    get sensible defaults (empty lists, False, etc.).
    """

def get_project_expectations(config: dict) -> dict:
    """
    Extract the 'expectations' section from a project config.

    Returns dict with keys: no_derived_expected (set[str]),
    pipelines (list[dict]). Missing keys get sensible defaults.
    """
```

### Step 2.3: Update session_viewer.py

Replace `PROJECT_CONFIG` dict with calls to `list_project_configs()` and
`load_project_config()`. The viewer still needs to read job_types,
derived_columns, etc. — map from the YAML structure to what the viewer
currently expects. This is the one place where some adapter logic is needed.

### DONE WHEN (Phase 2):
- [ ] `PROJECT_CONFIG` dict is removed from session_viewer.py
- [ ] Two YAML files exist with equivalent information
- [ ] `config.py` can load by project name with user override support
- [ ] session_viewer.py dropdown is populated from `list_project_configs()`
- [ ] **VERIFY**: `python -c "from aind_session_utils.config import list_project_configs; print([c['name'] for c in list_project_configs()])"` prints both project names
- [ ] **VERIFY**: session_viewer.py has no import errors
- [ ] **STOP.** Report what changed. Ask the human to start the Panel viewer
      and verify: same dropdown options, same query behavior when loading
      sessions. If issues, fix only those issues. Once confirmed working,
      suggest commit message: `refactor: phase 2 — project configs to YAML`.
      Wait for human to commit.

---

## PHASE 3: Create SessionResult dataclass and build_sessions()

**⚠️ THIS IS THE HIGHEST-RISK PHASE.** The split of `build_session_table()`
into `build_sessions()` + a presentation wrapper is where subtle bugs can
creep in. The most common failure: a field that was populated in the old
monolithic function doesn't get mapped to the right SessionResult field, so a
table column goes blank or shows wrong data. Work carefully and check the
column mapping explicitly.

**Goal:** Create the structured session data model. Refactor
`build_session_table()` into two parts: `build_sessions()` (in the library,
returns SessionResult objects) and a presentation function (in
session_viewer.py, converts SessionResult to table rows with HTML). At the
end of this phase, session_viewer.py does zero querying or joining — it
receives SessionResult objects and renders them. Every table column, icon,
and clickable cell must still work exactly as before.

### Step 3.1: Create `session.py` with dataclasses

```python
# session.py — session data model and assembly

from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class DerivedAssetInfo:
    """One derived asset found for a session."""
    asset_name: str
    docdb_id: str | None          # DocDB _id field
    modalities: frozenset[str]    # modalities in this derived asset
    co_asset_id: str | None       # Code Ocean data asset UUID
    co_log_url: str | None        # CO output log URL, or 'pending'
    pipeline_status: str | None   # 'succeeded'|'failed'|'running'|None

@dataclass(frozen=True)
class SessionResult:
    """Everything found about a session across all available sources."""
    # Identity
    session_name: str
    subject_id: str
    session_datetime: datetime | None
    raw_modalities: frozenset[str]

    # Rig-side
    manifest_status: str | None   # 'complete'|'pending'|None
    manifest_rig: str | None
    watchdog_events: list[dict]   # [{datetime, source, action, message}, ...]
    rig_log_path: str | None

    # Upload
    dts_status: str | None        # 'success'|'failed'|'running'|'queued'|None
    dts_job_id: str | None
    dts_job_url: str | None

    # Raw asset
    raw_asset_name: str | None
    raw_docdb_id: str | None
    raw_co_asset_id: str | None

    # Derived (zero or more)
    derived_assets: tuple[DerivedAssetInfo, ...]

    # Source tracking
    sources_queried: frozenset[str]
    sources_unavailable: frozenset[str]
```

### Step 3.2: Create `build_sessions()`

```python
def build_sessions(
    date_from: datetime,
    date_to: datetime,
    project_config: dict | None = None,
    subject_filter: str | None = None,
) -> list[SessionResult]:
    """
    Query all available sources and return SessionResult objects.

    This is the main entry point for the library. It:
    1. Queries DTS for jobs in the date range
    2. Queries DocDB for raw and derived records
    3. Queries Code Ocean for asset IDs and log URLs
    4. Queries watchdog for log events
    5. Loads rig manifests (if project config enables it)
    6. Looks up rig logs
    7. Joins everything by session name
    8. Returns a list of SessionResult, sorted newest-first

    Args:
        date_from: Start of date range (UTC)
        date_to: End of date range (UTC)
        project_config: Parsed project config dict (from config.py).
            If None, queries all sources without project-specific filtering.
        subject_filter: Optional subject ID to filter by.

    Returns:
        List of SessionResult objects, one per session found.
    """
```

**Implementation approach:** Extract the joining logic from the existing
`build_session_table()` function. The core logic (indexing DTS jobs by
session name, splitting DocDB records into raw/derived, the session loop
that builds rows) stays the same. The difference is:

- Instead of building a dict with HTML cell values, build a SessionResult
- Instead of calling `dts_cell()`, `asset_cell()`, etc., just store the
  raw status values
- Instead of returning a DataFrame, return a list of SessionResult

### Step 3.3: Rewrite build_session_table() in session_viewer.py

The `build_session_table()` function in session_viewer.py becomes a
thin presentation layer:

```python
def build_session_table(
    sessions: list[SessionResult],
    project_config: dict | None,
) -> pd.DataFrame:
    """Convert SessionResult objects to a DataFrame with HTML cells.
    
    This is purely presentation. It takes assembled SessionResult objects
    and renders each field as an HTML table cell using the *_cell() functions.
    """
```

All the `*_cell()` functions stay in session_viewer.py and are called here.

### Step 3.4: Update on_load()

In session_viewer.py's `on_load()` callback, replace the direct source
queries with a call to `build_sessions()`, then pass the results to the
new `build_session_table()`.

### DONE WHEN (Phase 3):
- [ ] `SessionResult` and `DerivedAssetInfo` dataclasses exist in session.py
- [ ] `build_sessions()` exists and returns `list[SessionResult]`
- [ ] `build_session_table()` in session_viewer.py takes `list[SessionResult]`
      as input (not raw source data)
- [ ] All `*_cell()` HTML functions remain in session_viewer.py
- [ ] `session_viewer.py` has zero query/joining logic — only presentation
- [ ] **VERIFY**: `python -c "from aind_session_utils.session import SessionResult, build_sessions"` works
- [ ] **VERIFY**: session_viewer.py has no import errors
- [ ] **STOP.** This is the highest-risk phase. Report:
      - Exactly how each SessionResult field maps to each table column
      - Any judgment calls about where logic lives
      - Any fields from the old build_session_table that didn't map cleanly
      Ask the human to start the Panel viewer and carefully verify: same
      columns in same order, same icons, same click-to-modal behavior. If
      issues, fix only those issues — do not start Phase 4. Once confirmed
      working, suggest commit message: `refactor: phase 3 — SessionResult
      dataclass and build_sessions`. Wait for human to commit.

---

## PHASE 4: Completeness logic

**Goal:** Add modality-based completeness evaluation. At the end of this
phase, the orphan toggle ("only show sessions missing derived asset") uses
real modality set math instead of a simple boolean. The same sessions should
show as missing — if different ones show, something is wrong.

### Step 4.1: Create `completeness.py`

```python
# completeness.py — pure set math, no I/O

from dataclasses import dataclass

@dataclass(frozen=True)
class CompletenessResult:
    status: str                    # 'complete'|'partial'|'no_derived'|'no_raw_asset'
    expected_modalities: frozenset[str]
    covered_modalities: frozenset[str]
    missing_modalities: frozenset[str]
    excluded_modalities: frozenset[str]

def check_completeness(
    session: SessionResult,
    no_derived_expected: frozenset[str] = frozenset(),
) -> CompletenessResult:
    """
    Check whether a session's processing is complete.

    Logic:
    1. expected = session.raw_modalities - no_derived_expected
    2. covered = union of all derived_assets' modalities
    3. missing = expected - covered
    4. status based on what's missing

    Without project config (no_derived_expected is empty): all raw modalities
    must have derived coverage. Conservative default.

    With project config: no_derived_expected suppresses modalities that
    are collected but intentionally not processed (e.g., behavior-videos).
    """
```

### Step 4.2: Update viewer to use completeness

Replace the `_has_derived` boolean logic in session_viewer.py with
`check_completeness()`. The orphan toggle becomes "only show sessions where
status != 'complete'".

### DONE WHEN (Phase 4):
- [ ] `check_completeness()` exists and handles edge cases:
      - Session with no raw asset → 'no_raw_asset'
      - Session with raw but no derived → 'no_derived'
      - Session with partial coverage → 'partial'
      - Session with full coverage → 'complete'
      - Session with behavior-videos excluded → still 'complete'
- [ ] Viewer orphan toggle uses completeness status
- [ ] **VERIFY**: `python -c "from aind_session_utils.completeness import check_completeness"` works
- [ ] **VERIFY**: session_viewer.py has no import errors
- [ ] **STOP.** Report what changed. Ask the human to start the Panel viewer
      and verify: toggle the orphan checkbox and confirm the same sessions
      appear as before. If different sessions show, report which ones changed
      and why. Fix only those issues. Once confirmed working, suggest commit
      message: `refactor: phase 4 — completeness logic with modality set
      math`. Wait for human to commit.

---

## PHASE 5: Persistent store

**Goal:** Replace `pn.cache` decorators with a persistent parquet-based local
store. At the end of this phase, session data is saved to disk between runs.
The first load for a date range queries all sources (same as before). Subsequent
loads for the same range return settled sessions from parquet instantly and only
re-query unsettled sessions. The viewer works identically but feels faster on
repeat loads. At the
end of this phase, session data persists across server restarts. The first
load for a date range hits all sources (same speed as before). Subsequent
loads for the same range are much faster because settled sessions come from
local parquet files and only unsettled sessions get re-queried.

### Step 5.1: Create `store.py`

```python
# store.py — persistent session store

from abc import ABC, abstractmethod
from pathlib import Path
import os
import pandas as pd

_DEFAULT_STORE_DIR = Path.home() / ".cache" / "aind_session_utils"

def get_store_dir() -> Path:
    """Return store directory from env var or default."""
    return Path(os.environ.get("AIND_SESSION_CACHE_DIR", str(_DEFAULT_STORE_DIR)))

class SessionStore(ABC):
    """Abstract interface for session persistence."""

    @abstractmethod
    def load_sessions(self, session_names: set[str] | None = None) -> pd.DataFrame:
        """Load session rows. None = load all."""

    @abstractmethod
    def load_derived_assets(self, session_names: set[str] | None = None) -> pd.DataFrame:
        """Load derived asset rows for given sessions."""

    @abstractmethod
    def save_sessions(self, df: pd.DataFrame) -> None:
        """Upsert sessions by session_name."""

    @abstractmethod
    def save_derived_assets(self, df: pd.DataFrame) -> None:
        """Upsert derived assets. Keep newest per (session_name, modalities)."""

    @abstractmethod
    def get_unsettled(self) -> pd.DataFrame:
        """Return sessions where _settled is False."""

    @abstractmethod
    def mark_settled(self, session_names: set[str]) -> None:
        """Mark sessions as settled."""

    @abstractmethod
    def refresh(self, session_names: set[str]) -> None:
        """Force sessions back to unsettled for re-query."""

    @abstractmethod
    def clear(self) -> None:
        """Delete all stored data. For troubleshooting."""


class ParquetSessionStore(SessionStore):
    """
    Local parquet implementation.

    Files:
        {store_dir}/sessions.parquet       — one row per session
        {store_dir}/derived_assets.parquet  — one row per derived asset

    sessions.parquet columns:
        session_name (PK), subject_id, session_datetime,
        raw_modalities (comma-separated str), manifest_status,
        manifest_rig, dts_status, dts_job_id, raw_asset_name,
        raw_docdb_id, raw_co_asset_id, _settled (bool),
        _last_updated (datetime)

    derived_assets.parquet columns:
        session_name (FK), asset_name, docdb_id,
        modalities (comma-separated str), co_asset_id,
        co_log_url, pipeline_status
    """
```

### Step 5.2: Integrate store into build_sessions()

Update `build_sessions()` to:
1. Load from store for the requested date range
2. Return settled sessions immediately (no re-query)
3. Re-query only unsettled sessions and new (not-in-store) sessions
4. Merge results back into store
5. Recompute _settled using check_completeness()
6. Save updated store

### Step 5.3: Remove pn.cache decorators

Remove `@pn.cache` from all source functions that moved to the subpackage.
The persistent store replaces this caching.

### Step 5.4: Migrate CO run cache

Move `co_pipeline_run_cache.json` into the store directory
(`~/.cache/aind_session_utils/co_run_cache.json`). Update path in
`sources/codeocean.py`.

### DONE WHEN (Phase 5):
- [ ] `ParquetSessionStore` reads and writes parquet files
- [ ] `build_sessions()` uses the store (load → query unsettled → save)
- [ ] Second call to `build_sessions()` for the same date range is fast
      (settled sessions not re-queried)
- [ ] `store.refresh(session_names)` forces re-query for specific sessions
- [ ] `store.clear()` wipes the store directory
- [ ] No `@pn.cache` decorators remain on subpackage functions
- [ ] **VERIFY**: `python -c "from aind_session_utils.store import ParquetSessionStore"` works
- [ ] **VERIFY**: session_viewer.py has no import errors
- [ ] **STOP.** Report what changed. Ask the human to start the Panel viewer
      and verify: load sessions twice for the same date range — second load
      should be noticeably faster. Also test: does the viewer still show the
      same data as before? Fix only reported issues. Once confirmed working,
      suggest commit message: `refactor: phase 5 — persistent parquet store
      replacing pn.cache`. Wait for human to commit.

---

## PHASE 6: Final cleanup

**Goal:** Polish the public API surface and verify the separation is clean.
At the end of this phase, `aind_session_utils` has zero Panel dependency and
a clean `__init__.py` that exports everything a consumer needs.
`session_viewer.py` is purely presentation — no queries, no joining, no
caching. This is the state we want before extracting to a separate repo.

### Step 6.1: Update `__init__.py` exports

```python
from aind_session_utils.naming import (
    get_session_name, parse_session_name, session_date,
    session_datetime, get_modalities,
)
from aind_session_utils.session import SessionResult, DerivedAssetInfo, build_sessions
from aind_session_utils.completeness import check_completeness, CompletenessResult
from aind_session_utils.config import load_project_config, list_project_configs
from aind_session_utils.store import ParquetSessionStore, get_store_dir
```

### Step 6.2: Verify session_viewer.py is thin

session_viewer.py should now contain ONLY:
- Imports from aind_session_utils
- HTML cell rendering functions (`dts_cell`, `asset_cell`, `co_log_cell`,
  `co_asset_link_cell`, `rig_log_cell`, `watchdog_cell`, `_log_modal_html`,
  `sort_record_for_display`)
- `build_session_table()` — converts SessionResult list to DataFrame with HTML
- `build_panel_app()` — Panel widgets, layout, event handlers
- `app = build_panel_app()` and `app.servable()`

No query functions, no DocDB/DTS/CO client setup, no caching logic, no
session name parsing, no project config dict.

### DONE WHEN (Phase 6):
- [ ] `aind_session_utils` has zero dependency on Panel
- [ ] `session_viewer.py` has zero query or joining logic
- [ ] All imports in session_viewer.py come from aind_session_utils
- [ ] **VERIFY**: `grep -r "import panel\|from panel\|import pn" src/aind_session_utils/` returns nothing
- [ ] **VERIFY**: session_viewer.py has no import errors
- [ ] **STOP.** Report a final summary:
      - Files created in aind_session_utils/ (list them all)
      - Approximate line count of session_viewer.py before vs. after
      - Any judgment calls or deviations from this plan
      Ask the human to start the Panel viewer for a final end-to-end test.
      Once confirmed working, suggest commit message: `refactor: phase 6 —
      final cleanup and public API`. Wait for human to commit.

---

## IMPORTANT CONTEXT

### Session name is the universal join key

Format: `{subject_id}_{YYYY-MM-DD}_{HH-MM-SS}`
Example: `822683_2026-02-26_16-59-38`

Raw asset names may include a modality prefix (`behavior_822683_...`).
Derived asset names include a processing suffix (`..._processed_2026-...`).
`get_session_name()` strips both to get the canonical key.

### Completeness is set math on modalities

Raw asset declares collected modalities (e.g., {behavior, fib, behavior-videos}).
Derived assets each declare their modalities.
Complete = all collected modalities covered by derived assets
(minus modalities the project config says aren't processed).

### The persistent store is a materialized view, not a TTL cache

Data does not expire. Immutable facts (asset IDs, names, modalities) are
stored forever. Only "unsettled" sessions (with in-progress or missing
pipeline results) are re-queried. Sessions can be forced back to unsettled
via `store.refresh()` for the reprocessing case.

### Source availability varies

DTS and rig logs/manifests require AIND on-prem network. DocDB and Code Ocean
are cloud-accessible. Each source module has `is_available()`. The library
reports which sources were reachable via `SessionResult.sources_unavailable`.
Missing sources mean "unknown," not "doesn't exist."

### Shared constants

`AIND_LOGS_DIR` is used by both `sources/manifests.py` and `sources/rig_logs.py`.
Define it in one place (e.g., a `constants.py` or in one module) and import
from the other. Do not duplicate it.

Similarly, if multiple source modules need the logger, create it once at the
package level (`__init__.py` or a shared module) and import it.