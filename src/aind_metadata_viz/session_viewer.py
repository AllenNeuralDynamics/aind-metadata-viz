"""
Session Status Viewer

Provides an end-to-end pipeline status view for data collection sessions.
The project is selectable via dropdown; add entries to PROJECT_CONFIG to extend.

ARCHITECTURE:
    Both data sources are queried server-side:

    - DocDB (via aind-data-access-api): asset registration records, cached 1hr.
      No time limit; shows all sessions that made it to registration.
      Searches V1 and/or V2 DB as configured per project; V2 takes precedence
      when the same asset exists in both.

    - DTS REST API (via requests): job status from http://aind-data-transfer-service.
      The DTS is on the AIND internal network, so this app must be run from the AIND
      network or VPN (locally or deployed on-prem). Cached 5min.

    Note: the DTS API has no CORS headers, so client-side JS fetch cannot be used.
    The server-side approach requires network access to http://aind-data-transfer-service.

DATA FLOW:
    1. User selects date range and clicks Load Sessions
    2. Server queries DTS API (paginated) for all jobs in the date range
    3. Server queries DocDB (V1 and/or V2) for project records (cached 1hr)
    4. Both are joined by session name and rendered as a status table

LIMITATIONS:
    - DTS API enforces a 14-day lookback window. For sessions older than 14 days,
      the DTS Status column shows "N/A (>14 days)".
    - Sessions that failed before reaching the DTS are not visible (Phase 2 scope).
    - Requires AIND network or VPN access for DTS data.

EXTENSION POINTS:
    - Add projects to PROJECT_CONFIG.
    - Tier 2 rig-side manifest detection: implement RigLogSource (see stub below).

URL PARAMETERS:
    - subject:   pre-fill subject ID filter (e.g. ?subject=822683)
    - date_from: pre-fill start date (e.g. ?date_from=2026-03-04)
    - date_to:   pre-fill end date   (e.g. ?date_to=2026-03-11)
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import requests as req
import pandas as pd
import panel as pn

from urllib.parse import quote

from aind_data_access_api.document_db import MetadataDbClient
from aind_metadata_viz.utils import TTL_HOUR

pn.extension("tabulator", "modal")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DTS_BASE_URL = "http://aind-data-transfer-service"
METADATA_PORTAL_BASE = "https://metadata-portal.allenneuraldynamics-test.org"
DTS_MAX_LOOKBACK_DAYS = 14
DTS_CACHE_TTL = 5 * 60  # 5 minutes — DTS data changes frequently

# Suffixes that mark a derived (processed) asset name
_DERIVED_MARKERS = ("_processed_", "_videoprocessed_", "_sorted_")

# ---------------------------------------------------------------------------
# PROJECT_CONFIG
#
# Each entry defines one dropdown option.  Keys:
#
#   job_types         dict[str, dict] — DTS job type → {"expected_pipelines": set[str]}
#                     expected_pipelines: modality abbreviations whose derived asset
#                     columns are applicable to this job type.  Pipelines not in this
#                     set will show "—" (N/A) rather than ⬜ (not yet reached).
#
#   docdb_project_names  list[str] — DocDB project_name values to query.  A single
#                        dropdown entry may span multiple DocDB project names.
#
#   docdb_versions    list[str] — which DocDB versions to search ("v1", "v2", or both).
#                     When the same asset exists in both, V2 takes precedence.
#
#   derived_columns   list[dict] — pipeline asset columns for this project.
#                     Each entry: {"label": str, "modalities": set[str]}
# ---------------------------------------------------------------------------

PROJECT_CONFIG: dict[str, dict] = {
    "Cognitive flexibility in patch foraging": {
        "job_types": {
            "vr_foraging_fiber": {"expected_pipelines": {"behavior", "fib"}},
            "vr_foraging_v2":    {"expected_pipelines": {"behavior"}},
        },
        "docdb_project_names": ["Cognitive flexibility in patch foraging"],
        "docdb_versions": ["v2"],
        "derived_columns": [
            {"label": "Behavior Asset", "modalities": {"behavior"}},
            {"label": "FIP Asset",      "modalities": {"fib", "fiber"}},
        ],
    },
    "Dynamic Foraging": {
        "job_types": {
            "dynamic_foraging_behavior_and_fiber": {"expected_pipelines": {"behavior", "fib"}},
            "dynamic_foraging_behavior_only":      {"expected_pipelines": {"behavior"}},
            "dynamic_foraging_compression":        {"expected_pipelines": {"behavior"}},
            "dynamic_foraging":                    {"expected_pipelines": {"behavior"}},
        },
        # Dynamic Foraging sessions span many DocDB project names across different PIs,
        # so filtering by project name is unreliable.  Instead, all dynamic foraging raw
        # assets in V1 share the "behavior_" name prefix — use that as the filter.
        "docdb_project_names": [],
        "docdb_name_regex": "^behavior_",
        "docdb_versions": ["v1", "v2"],
        "derived_columns": [
            {"label": "Behavior Asset", "modalities": {"behavior"}},
            {"label": "Video Asset",    "modalities": {"behavior-videos"}},
            {"label": "FIP Asset",      "modalities": {"fib", "fiber"}},
        ],
    },
}

# ---------------------------------------------------------------------------
# DocDB clients (V1 and V2)
# ---------------------------------------------------------------------------

docdb_client_v1 = MetadataDbClient(host="api.allenneuraldynamics.org", version="v1")
docdb_client_v2 = MetadataDbClient(host="api.allenneuraldynamics.org", version="v2")

_DOCDB_CLIENTS = {"v1": docdb_client_v1, "v2": docdb_client_v2}

logger = logging.getLogger("session_viewer")

# ---------------------------------------------------------------------------
# Tier 2 extension point: rig-side manifest / log detection
#
# Implement a concrete subclass and pass it to build_panel_app() when ready.
# The FileSystemRigLogSource reads from the network path where Alex Piet's
# cron job saves manifest listings.  Replace with a LokiLogSource (or similar)
# once the log server is available.
# ---------------------------------------------------------------------------

class RigLogSource:
    """
    Abstract source for rig-side manifest and watchdog log data (Tier 2).

    Subclass this and implement get_manifest_sessions() to surface sessions
    that failed before reaching the DTS (pre-watchdog failures).
    """

    def get_manifest_sessions(
        self,
        date_from: datetime,
        date_to: datetime,
    ) -> list[dict]:
        """
        Return a list of session dicts detected at the rig level.

        Each dict should contain at least:
            session_name (str), status (str), hostname (str)

        Raise NotImplementedError to signal "not configured" — the app will
        suppress Tier 2 columns rather than showing an error.
        """
        raise NotImplementedError


class FileSystemRigLogSource(RigLogSource):
    """
    Reads manifest listings saved by Alex Piet's cron job from the network share.

    Path: /allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs/

    NOT YET IMPLEMENTED.  Stub in place so the interface is defined.
    See build_plan.md §Tier 2 for details.
    """

    BASE_PATH = "/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs"

    def get_manifest_sessions(self, date_from, date_to):
        raise NotImplementedError("FileSystemRigLogSource not yet implemented")


# ---------------------------------------------------------------------------
# Name parsing helpers
# ---------------------------------------------------------------------------

def get_session_name(asset_name: str) -> str:
    """
    Extract the canonical session key ({subject_id}_{date}_{time}) from any asset name.

    Handles all naming conventions observed in DocDB:
      New raw:     '822683_2026-02-26_16-59-38'                              → '822683_2026-02-26_16-59-38'
      Old raw:     'behavior_789919_2025-07-11_19-48-01'                     → '789919_2025-07-11_19-48-01'
      New derived: '822683_2026-02-26_16-59-38_processed_2026-02-27_...'     → '822683_2026-02-26_16-59-38'
      Old derived: 'behavior_789919_2025-07-11_19-48-01_processed_2025-...'  → '789919_2025-07-11_19-48-01'
    """
    # Step 1: strip processing suffix
    for marker in _DERIVED_MARKERS:
        if marker in asset_name:
            asset_name = asset_name.split(marker)[0]
            break
    # Step 2: strip modality prefix (non-numeric first component)
    parts = asset_name.split("_")
    if parts and not parts[0].isdigit():
        return "_".join(parts[1:])
    return asset_name


def parse_session_name(session_name: str) -> tuple[str, str]:
    """
    Return (subject_id, display_datetime) from a session name.

    '822683_2026-02-26_16-59-38' → ('822683', '2026-02-26 16:59:38')
    """
    parts = session_name.split("_")
    subject_id = parts[0] if parts else session_name
    if len(parts) >= 3:
        dt_str = f"{parts[1]} {parts[2].replace('-', ':')}"
    elif len(parts) >= 2:
        dt_str = parts[1]
    else:
        dt_str = ""
    return subject_id, dt_str


def session_date(session_name: str) -> datetime | None:
    """Parse the session date from a session name as a UTC datetime, or None."""
    parts = session_name.split("_")
    if len(parts) >= 2:
        try:
            return datetime.strptime(parts[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def session_datetime(session_name: str) -> datetime | None:
    """Parse full acquisition datetime (date + time) from a session name, or None."""
    parts = session_name.split("_")
    if len(parts) >= 3:
        try:
            return datetime.strptime(
                f"{parts[1]} {parts[2]}", "%Y-%m-%d %H-%M-%S"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return session_date(session_name)


def get_modalities(record: dict) -> list[str]:
    """
    Return lowercased modality abbreviations from a DocDB record.

    Handles both V2 schema ("modalities") and V1 schema ("modality").
    """
    try:
        dd = record.get("data_description", {})
        # V2 uses "modalities", V1 uses "modality" (same list structure)
        mods = dd.get("modalities") or dd.get("modality") or []
        return [m["abbreviation"].lower() for m in mods if isinstance(m, dict)]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# JSON display helpers
# ---------------------------------------------------------------------------

def sort_record_for_display(obj: object) -> object:
    """
    Recursively reorder dict keys: flat (non-dict, non-list) values first
    (alphabetical), then nested values (alphabetical).  Makes the JSON modal
    easier to scan — important metadata floats to the top of each level.
    """
    if not isinstance(obj, dict):
        return obj
    flat = {k: obj[k] for k in sorted(obj) if not isinstance(obj[k], (dict, list))}
    nested = {k: sort_record_for_display(obj[k]) for k in sorted(obj) if isinstance(obj[k], (dict, list))}
    return {**flat, **nested}


# ---------------------------------------------------------------------------
# HTML cell helpers
# ---------------------------------------------------------------------------

_DTS_ICONS = {
    "success": "✅",
    "failed": "❌",
    "running": "⏳",
    "queued": "⏳",
    "up_for_retry": "⏳",
}


def dts_cell(job: dict | None, within_14_days: bool) -> tuple[str, str]:
    """
    Render the DTS status cell as an HTML string, and return the DTS URL (or "").

    Returns (html, url) — url is non-empty only when a task drill-down is available.
    """
    if not within_14_days:
        return '<span style="color:#888;">N/A (&gt;14 days)</span>', ""
    if job is None:
        return "⬜", ""
    state = job.get("job_state", "unknown")
    icon = _DTS_ICONS.get(state, "❓")
    dag_run_id = job.get("job_id", "")
    dag = job.get("dag_id", "transform_and_upload_v2")
    if dag_run_id:
        url = (
            f"{DTS_BASE_URL}/job_tasks_table"
            f"?dag_id={quote(dag)}&dag_run_id={quote(dag_run_id)}"
        )
        html = f'<span style="cursor:pointer;color:#1a73e8;text-decoration:underline">{icon} view tasks/logs</span>'
        return html, url
    return f"{icon} {state}", ""


def asset_cell(name: str | None) -> str:
    """Render an asset status cell as a clickable span (opens inline metadata modal)."""
    if not name:
        return "⬜"
    return '<span style="cursor:pointer;color:#1a73e8;text-decoration:underline">✅ view metadata</span>'


# ---------------------------------------------------------------------------
# Data fetching — both server-side
# ---------------------------------------------------------------------------

@pn.cache(ttl=TTL_HOUR)
def get_project_records(
    project_names: tuple[str, ...],
    versions: tuple[str, ...],
    name_regex: str = "",
) -> list[dict]:
    """
    Fetch all DocDB records (raw + derived) for the given project, across the
    specified DB versions.  Results are merged by asset name; V2 takes precedence
    over V1 when the same asset exists in both.  Cached for 1 hour.

    If name_regex is provided, records are filtered by asset name pattern instead
    of project name.  Useful when a project spans many unpredictable project names
    (e.g. Dynamic Foraging, where all raw assets share the "behavior_" prefix).
    """
    logger.info(
        "Querying DocDB for project records",
        extra={"projects": project_names, "versions": versions, "name_regex": name_regex},
    )
    projection = {
        "name": 1,
        "_id": 1,
        "subject.subject_id": 1,
        "data_description.data_level": 1,
        "data_description.modalities": 1,
        "data_description.modality": 1,
    }
    # Collect V1 first, then V2 so V2 naturally overwrites on name collision.
    by_name: dict[str, dict] = {}
    for version in ("v1", "v2"):
        if version not in versions:
            continue
        client = _DOCDB_CLIENTS[version]
        if name_regex:
            records = client.retrieve_docdb_records(
                filter_query={"name": {"$regex": name_regex}},
                projection=projection,
                limit=0,
                paginate_batch_size=500,
            )
            for r in records:
                by_name[r.get("name", "")] = r
        else:
            for project_name in project_names:
                records = client.retrieve_docdb_records(
                    filter_query={"data_description.project_name": project_name},
                    projection=projection,
                    limit=0,
                    paginate_batch_size=500,
                )
                for r in records:
                    by_name[r.get("name", "")] = r
    result = list(by_name.values())
    logger.info("DocDB query complete", extra={"count": len(result)})
    return result


@pn.cache(ttl=DTS_CACHE_TTL)
def get_raw_records_by_names(
    names: tuple[str, ...],
    versions: tuple[str, ...],
) -> list[dict]:
    """
    Fast $in lookup for raw records by exact asset name.

    Used in Phase 1 of two-phase loading: DTS job names are the exact
    DocDB raw asset names, so this query uses the name index (<0.2s).
    Cached for 5 minutes to match DTS cache lifetime.
    """
    if not names:
        return []
    projection = {
        "name": 1,
        "_id": 1,
        "subject.subject_id": 1,
        "data_description.data_level": 1,
        "data_description.modalities": 1,
        "data_description.modality": 1,
    }
    by_name: dict[str, dict] = {}
    for version in ("v1", "v2"):
        if version not in versions:
            continue
        client = _DOCDB_CLIENTS[version]
        records = client.retrieve_docdb_records(
            filter_query={"name": {"$in": list(names)}},
            projection=projection,
            limit=0,
        )
        for r in records:
            by_name[r.get("name", "")] = r
    logger.info("Phase 1 raw $in query", extra={"count": len(by_name), "names_queried": len(names)})
    return list(by_name.values())


@pn.cache(ttl=TTL_HOUR)
def get_derived_records_by_input_names(
    input_names: tuple[str, ...],
    versions: tuple[str, ...],
) -> list[dict]:
    """
    Fetch derived DocDB records by their input_data_name field.

    Derived assets store the name of their source raw asset in
    data_description.input_data_name.  Using $in on this field gives us
    exactly the derived records for the sessions found in Phase 1.
    This field is not indexed so the query is slow (~5-8s) — call from
    a background thread.  Cached for 1 hour.
    """
    if not input_names:
        return []
    projection = {
        "name": 1,
        "_id": 1,
        "subject.subject_id": 1,
        "data_description.data_level": 1,
        "data_description.modalities": 1,
        "data_description.modality": 1,
    }
    by_name: dict[str, dict] = {}
    for version in ("v1", "v2"):
        if version not in versions:
            continue
        client = _DOCDB_CLIENTS[version]
        records = client.retrieve_docdb_records(
            filter_query={"data_description.input_data_name": {"$in": list(input_names)}},
            projection=projection,
            limit=0,
            paginate_batch_size=500,
        )
        for r in records:
            by_name[r.get("name", "")] = r
    logger.info("Phase 2 derived input_data_name $in query", extra={"count": len(by_name)})
    return list(by_name.values())


@pn.cache(ttl=TTL_HOUR)
def get_full_record(name: str) -> dict | None:
    """
    Fetch the complete DocDB record for a single asset by name.

    Tries V2 first (newer schema), falls back to V1.  Returns None if not found.
    Cached for 1 hour — individual records rarely change.
    """
    for version in ("v2", "v1"):
        client = _DOCDB_CLIENTS[version]
        records = client.retrieve_docdb_records(
            filter_query={"name": name},
            limit=1,
        )
        if records:
            return records[0]
    return None


def filter_records_by_date(
    records: list[dict],
    date_from: datetime,
    date_to: datetime,
) -> list[dict]:
    """Filter records by the date encoded in the asset name."""
    result = []
    for r in records:
        d = session_date(get_session_name(r.get("name", "")))
        if d and date_from <= d <= date_to:
            result.append(r)
    return result


@pn.cache(ttl=DTS_CACHE_TTL)
def get_dts_jobs(date_from_iso: str, date_to_iso: str) -> tuple[list[dict], str | None]:
    """
    Fetch DTS jobs server-side, paginating as needed.

    Returns (jobs_list, error_message_or_None).
    Cached for 5 minutes since DTS data changes frequently.
    """
    all_jobs: list[dict] = []
    offset = 0
    page_limit = 500
    total: int | None = None

    try:
        while total is None or len(all_jobs) < total:
            params: dict = {
                "execution_date_gte": date_from_iso,
                "execution_date_lte": date_to_iso,
                "page_limit": page_limit,
                "page_offset": offset,
                "order_by": "-execution_date",
            }
            resp = req.get(
                f"{DTS_BASE_URL}/api/v1/get_job_status_list",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            jobs: list[dict] = data.get("job_status_list", [])
            if total is None:
                total = data.get("total_entries", 0)
            all_jobs.extend(jobs)
            offset += len(jobs)
            if not jobs:
                break
        return all_jobs, None
    except Exception as e:
        return [], str(e)


# ---------------------------------------------------------------------------
# Table builder
# ---------------------------------------------------------------------------

def build_session_table(
    dts_jobs: list[dict],
    all_docdb_records: list[dict],
    job_types: dict[str, dict],
    derived_columns: list[dict],
    date_from: datetime,
    date_to: datetime,
) -> pd.DataFrame:
    """
    Build a DataFrame with one row per session, joining DTS and DocDB by session name.

    job_types maps job_type name → config dict with 'expected_pipelines'.
    derived_columns is a list of {"label": str, "modalities": set[str]} dicts that
    drives which pipeline asset columns appear in the table.

    Sessions whose job_type is not in job_types are excluded from the table.
    For pipelines not in a session's expected_pipelines, '—' is shown instead of ⬜.
    For sessions with no DTS job (>14 days), expected_pipelines is unknown and ⬜ is used.

    all_docdb_records is the full unfiltered project record set. Date filtering is only
    applied to DocDB-only sessions (those not present in DTS), so that sessions collected
    one day before the range start but uploaded within the range still show their raw asset.
    """
    now_utc = datetime.now(tz=timezone.utc)
    cutoff_14d = now_utc - timedelta(days=DTS_MAX_LOOKBACK_DAYS)

    # Index DTS jobs by canonical session name (filter to relevant job types).
    # DTS job names may include a modality prefix (e.g. "behavior_829489_...") so
    # we normalise via get_session_name() to match the DocDB index key.
    dts_by_name: dict[str, dict] = {
        get_session_name(j["name"]): j
        for j in dts_jobs
        if j.get("job_type") in job_types
    }

    # Index ALL DocDB records by session name, split by raw vs derived.
    # We index everything so that a DTS session whose name-date falls just outside
    # the selected range can still find its DocDB record.
    raw_by_session: dict[str, dict] = {}
    derived_by_session: dict[str, list[dict]] = {}

    for r in all_docdb_records:
        name = r.get("name", "")
        sname = get_session_name(name)
        data_level = r.get("data_description", {}).get("data_level", "")
        is_raw = data_level == "raw" or (
            not data_level and not any(m in name for m in _DERIVED_MARKERS)
        )
        if is_raw:
            raw_by_session[sname] = r
        else:
            derived_by_session.setdefault(sname, []).append(r)

    # DTS sessions: date-filtered by execution_date via the API — include all.
    # DocDB-only sessions: filter by the date encoded in the session name.
    docdb_only: set[str] = set()
    for sname in raw_by_session:
        if sname not in dts_by_name:
            d = session_date(sname)
            if d is not None and date_from <= d <= date_to:
                docdb_only.add(sname)
    all_sessions = set(dts_by_name.keys()) | docdb_only

    _epoch = datetime.min.replace(tzinfo=timezone.utc)

    rows = []
    for sname in sorted(
        all_sessions,
        key=lambda s: session_datetime(s) or _epoch,
        reverse=True,
    ):
        subject_id, dt_str = parse_session_name(sname)
        d = session_date(sname)
        within_14d = d is None or d >= cutoff_14d

        dts_job = dts_by_name.get(sname)
        raw = raw_by_session.get(sname)
        derived = derived_by_session.get(sname, [])

        # Determine which pipelines are expected for this session.
        # Unknown (no DTS job) → None, meaning fall back to ⬜ for all pipelines.
        job_type = dts_job.get("job_type") if dts_job else None
        expected = job_types[job_type]["expected_pipelines"] if job_type else None

        modalities = ", ".join(get_modalities(raw)) if raw else ""

        # Prefer subject_id from DocDB metadata; fall back to name parsing for
        # DTS-only sessions that have no raw record yet.
        if raw:
            subject_id = (raw.get("subject") or {}).get("subject_id") or subject_id

        # Show the real asset name so users can search for it in DocDB / the portal.
        # The canonical sname is the normalised join key, which strips prefixes like
        # "behavior_" that are part of the actual asset name.
        display_name = raw["name"] if raw else (dts_job["name"] if dts_job else sname)

        raw_name = raw["name"] if raw else ""
        dts_html, dts_url = dts_cell(dts_job, within_14d)
        row: dict = {
            "Subject": subject_id,
            "Session Date": dt_str,
            "Modalities": modalities,
            "Session Name": display_name,
            "Rig Log": '<span style="color:#aaa;font-style:italic">(not yet implemented)</span>',
            "DTS Upload": dts_html,
            "_dts_url": dts_url,
            "Raw Asset": asset_cell(raw_name or None),
            "_name_Raw Asset": raw_name,
        }
        for col in derived_columns:
            if expected is not None and not col["modalities"] & expected:
                row[col["label"]] = "—"
                row[f"_name_{col['label']}"] = ""
            else:
                record = next(
                    (r for r in derived if col["modalities"] & set(get_modalities(r))),
                    None,
                )
                name = record["name"] if record else ""
                row[col["label"]] = asset_cell(name or None)
                row[f"_name_{col['label']}"] = name

        rows.append(row)

    fixed_cols = ["Subject", "Session Date", "Modalities", "Session Name",
                  "Rig Log", "DTS Upload", "Raw Asset"]
    derived_col_labels = [c["label"] for c in derived_columns]
    hidden_cols = ["_dts_url", "_name_Raw Asset"] + [f"_name_{c['label']}" for c in derived_columns]
    return pd.DataFrame(rows, columns=fixed_cols + derived_col_labels + hidden_cols)


# ---------------------------------------------------------------------------
# Panel app
# ---------------------------------------------------------------------------

def build_panel_app():
    today = datetime.now(tz=timezone.utc).date()
    default_from = today - timedelta(days=7)

    project_select = pn.widgets.Select(
        name="",
        options=list(PROJECT_CONFIG.keys()),
        width=380,
    )
    date_from_picker = pn.widgets.DatePicker(name="", value=default_from)
    date_to_picker = pn.widgets.DatePicker(name="", value=today)
    subject_input = pn.widgets.TextInput(
        placeholder="e.g. 822683",
        width=220,
    )
    load_button = pn.widgets.Button(name="Load Sessions", button_type="primary")
    status_md = pn.pane.Markdown("", sizing_mode="stretch_width")
    table_col = pn.Column(sizing_mode="stretch_width")

    # Inspector modal — hidden until a cell is clicked; body content is swapped per click
    _modal_body = pn.Column(sizing_mode="stretch_both")
    _inspector_modal = pn.layout.Modal(
        _modal_body,
        show_close_button=True,
        background_close=True,
        stylesheets=["""
            .dialog-content {
                width: 95vw !important;
                height: 95vh !important;
                max-width: 95vw !important;
                max-height: 95vh !important;
                overflow: auto;
                display: flex;
                flex-direction: column;
            }
        """],
    )

    def on_load(_event=None):
        if not date_from_picker.value or not date_to_picker.value:
            status_md.object = "❌ Please select a date range."
            return

        project_name = project_select.value
        cfg = PROJECT_CONFIG[project_name]
        job_types: dict[str, dict] = cfg["job_types"]
        job_type_names: set[str] = set(job_types.keys())
        docdb_project_names: tuple[str, ...] = tuple(cfg["docdb_project_names"])
        docdb_versions: tuple[str, ...] = tuple(cfg["docdb_versions"])
        docdb_name_regex: str = cfg.get("docdb_name_regex", "")
        derived_columns: list[dict] = cfg["derived_columns"]

        load_button.disabled = True
        status_md.object = "⏳ Loading..."
        table_col[:] = []

        date_from = datetime(
            date_from_picker.value.year,
            date_from_picker.value.month,
            date_from_picker.value.day,
            tzinfo=timezone.utc,
        )
        date_to = datetime(
            date_to_picker.value.year,
            date_to_picker.value.month,
            date_to_picker.value.day,
            23, 59, 59,
            tzinfo=timezone.utc,
        )

        subject = subject_input.value.strip()

        # DTS — server-side
        dts_jobs, dts_error = get_dts_jobs(date_from.isoformat(), date_to.isoformat())

        # DocDB — strategy depends on project config
        try:
            if docdb_name_regex:
                # Dynamic Foraging: sessions span many project names, so we can't
                # filter by project_name.  Instead we use the DTS job names (which
                # equal raw DocDB asset names) for a fast $in raw lookup, then
                # query derived records by input_data_name $in.
                dts_names = tuple(
                    j["name"] for j in dts_jobs if j.get("job_type") in job_type_names
                )
                raw_records = get_raw_records_by_names(dts_names, docdb_versions)
                derived_records = get_derived_records_by_input_names(dts_names, docdb_versions)
                all_records = raw_records + derived_records
            else:
                all_records = get_project_records(docdb_project_names, docdb_versions)
        except Exception as exc:
            status_md.object = f"❌ DocDB query failed: {exc}"
            load_button.disabled = False
            return

        records_in_range = filter_records_by_date(all_records, date_from, date_to)

        if dts_error:
            status_md.object = (
                f"⚠️ **DTS unavailable** _(requires AIND network or VPN)_: {dts_error}\n\n"
                f"Showing {len(records_in_range)} DocDB records only."
            )
        else:
            n_dts = sum(1 for j in dts_jobs if j.get("job_type") in job_type_names)
            status_md.object = (
                f"**{n_dts} DTS jobs** · "
                f"**{len(records_in_range)} DocDB records** · "
                f"{date_from.date()} → {date_to.date()} · "
                f"_DTS cache: 5min, DocDB cache: 1hr_"
            )

        if subject:
            dts_jobs = [j for j in dts_jobs if subject in j.get("name", "")]
            all_records = [r for r in all_records if subject in r.get("name", "")]

        df = build_session_table(
            dts_jobs, all_records, job_types, derived_columns, date_from, date_to
        )

        if df.empty:
            table_col[:] = [pn.pane.Markdown("_No sessions found for the selected filters._")]
        else:
            html_cols = ["Rig Log", "DTS Upload", "Raw Asset"] + [c["label"] for c in derived_columns]
            hidden_cols = ["_dts_url", "_name_Raw Asset"] + [f"_name_{c['label']}" for c in derived_columns]
            tab = pn.widgets.Tabulator(
                df,
                formatters={c: {"type": "html"} for c in html_cols if c in df.columns},
                hidden_columns=hidden_cols,
                sizing_mode="stretch_width",
                show_index=False,
                disabled=True,
                header_filters=True,
                page_size=50,
                stylesheets=["""
                    .tabulator-row:nth-child(even) { background-color: #f5f5f5 !important; }
                    .tabulator-row:nth-child(even):hover { background-color: #e8e8e8 !important; }
                """],
            )

            def on_cell_click(event, _df=df):
                row = _df.iloc[event.row]
                col = event.column

                if col == "DTS Upload":
                    url = str(row.get("_dts_url", ""))
                    if not url:
                        return
                    _modal_body[:] = [pn.pane.HTML(
                        f'<iframe src="{url}" style="width:100%;height:100%;min-height:85vh;border:none;flex:1;"></iframe>',
                        sizing_mode="stretch_both",
                    )]
                    _inspector_modal.show()
                    return

                name_col = f"_name_{col}"
                if name_col not in _df.columns:
                    return
                asset_name = str(row.get(name_col, ""))
                if not asset_name:
                    return
                title = pn.pane.Markdown(f"**{asset_name}**",
                                         styles={"font-weight": "bold", "margin-bottom": "6px"})
                json_pane = pn.pane.JSON({"loading": "fetching record…"}, depth=1,
                                         sizing_mode="stretch_width",
                                         styles={"overflow": "auto", "max-height": "88vh"})
                _modal_body[:] = [title, json_pane]
                _inspector_modal.show()
                record = get_full_record(asset_name)
                json_pane.object = (
                    sort_record_for_display(json.loads(json.dumps(record, default=str)))
                    if record else {"error": f"Record not found: {asset_name}"}
                )

            tab.on_click(on_cell_click)
            table_col[:] = [tab]
        load_button.disabled = False

    load_button.on_click(on_load)

    if pn.state.location:
        # Keep sync so URL stays updated when the user changes widgets and re-runs.
        pn.state.location.sync(project_select, {"value": "project"})
        pn.state.location.sync(subject_input, {"value": "subject"})
        pn.state.location.sync(date_from_picker, {"value": "date_from"})
        pn.state.location.sync(date_to_picker, {"value": "date_to"})

        # Auto-run when URL params arrive from the browser.  pn.state.onload fires
        # before the browser sends location data, so we watch location.search instead.
        _initial_load_done = [False]

        def _on_search_arrive(event):
            if _initial_load_done[0] or not event.new:
                return
            _initial_load_done[0] = True
            from urllib.parse import parse_qs
            params = parse_qs(event.new.lstrip("?"))
            if not params:
                return
            if "project" in params:
                project = params["project"][0]
                if project in PROJECT_CONFIG:
                    project_select.value = project
            if "subject" in params:
                subject_input.value = params["subject"][0]
            if "date_from" in params:
                try:
                    date_from_picker.value = datetime.strptime(
                        params["date_from"][0], "%Y-%m-%d"
                    ).date()
                except ValueError:
                    pass
            if "date_to" in params:
                try:
                    date_to_picker.value = datetime.strptime(
                        params["date_to"][0], "%Y-%m-%d"
                    ).date()
                except ValueError:
                    pass
            on_load()

        pn.state.location.param.watch(_on_search_arrive, "search")

    header = pn.pane.Markdown(
        "# Session Status Viewer\n\n"
        "Joins DTS job status with DocDB asset records. "
        "_Requires AIND network or VPN._",
        sizing_mode="stretch_width",
    )

    legend = pn.pane.Markdown(
        "**Status:** ✅ complete/registered &nbsp;&nbsp; "
        "❌ failed &nbsp;&nbsp; "
        "⏳ running/queued &nbsp;&nbsp; "
        "⬜ not yet reached &nbsp;&nbsp; "
        "— not applicable &nbsp;&nbsp; "
        "_(not yet implemented)_ coming soon &nbsp;&nbsp; "
        "_DTS and asset cells open an inline viewer._",
        styles={
            "background": "#f0f4ff",
            "padding": "8px 12px",
            "border-radius": "5px",
            "font-size": "0.9em",
        },
        sizing_mode="stretch_width",
    )

    controls = pn.Row(
        pn.Column("**Project**", project_select),
        pn.Spacer(width=20),
        pn.Column("**Date range**", pn.Row("From", date_from_picker, pn.Spacer(width=10), "To", date_to_picker)),
        pn.Spacer(width=20),
        pn.Column("**Subject ID (optional)**", subject_input),
        pn.Spacer(width=20),
        pn.Column("&nbsp;", load_button),
        align="start",
    )

    return pn.Column(
        header,
        legend,
        pn.layout.Divider(),
        controls,
        pn.Spacer(height=8),
        status_md,
        table_col,
        _inspector_modal,
        sizing_mode="stretch_width",
        min_width=900,
    )


app = build_panel_app()
app.servable(title="Session Status")
