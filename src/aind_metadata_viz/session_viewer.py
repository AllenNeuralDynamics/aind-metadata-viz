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
    - Rig manifest detection (Dynamic Foraging only) surfaces sessions that never
      reached the DTS. Requires the MANIFEST_DIR network share to be mounted.
    - Requires AIND network or VPN access for DTS data and rig manifests.

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
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import html as _html

import requests as req
import pandas as pd
import panel as pn

from urllib.parse import quote

from codeocean import CodeOcean
from codeocean.data_asset import DataAssetSearchParams, DataAssetState
from dotenv import load_dotenv
from aind_data_access_api.document_db import MetadataDbClient
from aind_metadata_viz.utils import TTL_HOUR

load_dotenv()  # picks up .env in the working directory (or any parent)

# ---------------------------------------------------------------------------
# Code Ocean client (optional — columns degrade gracefully if not configured)
# ---------------------------------------------------------------------------

_CO_DOMAIN: str = os.environ.get("CODEOCEAN_DOMAIN", "")
_co_client: CodeOcean | None = None
_co_url_cache: dict[str, str | None] = {}
_co_derived_id_cache: dict[str, str | None] = {}


def _get_co_client() -> CodeOcean | None:
    """Return a singleton CodeOcean client if credentials are configured."""
    global _co_client
    if _co_client is None:
        token = os.environ.get("CODEOCEAN_API_TOKEN")
        if _CO_DOMAIN and token:
            _co_client = CodeOcean(domain=_CO_DOMAIN, token=token)
    return _co_client


def get_co_output_url(asset_name: str) -> str | None:
    """
    Return the Code Ocean output log URL for a derived asset name.

    Returns:
        A URL string  — if the CO data asset is Ready
        'pending'     — if the asset exists but is not yet complete
        None          — if not found or CO is unavailable

    Results are cached in memory for the server lifetime (CO asset states
    are effectively immutable once Ready).
    """
    if asset_name in _co_url_cache:
        return _co_url_cache[asset_name]
    co = _get_co_client()
    if co is None:
        return None
    try:
        results = co.data_assets.search_data_assets(
            DataAssetSearchParams(query=asset_name, limit=5)
        )
        asset = next(
            (a for a in results.results if a.name == asset_name), None
        )
        if asset is None:
            result: str | None = None
            _co_derived_id_cache[asset_name] = None
        elif asset.state != DataAssetState.Ready:
            result = "pending"
            _co_derived_id_cache[asset_name] = asset.id
        else:
            result = f"{_CO_DOMAIN}/data-assets/{asset.id}/{asset.name}/output"
            _co_derived_id_cache[asset_name] = asset.id
    except Exception as e:
        logger.warning("CO log lookup failed for %s: %s", asset_name, e)
        result = None
    _co_url_cache[asset_name] = result
    return result


_co_raw_id_cache: dict[str, str | None] = {}
_co_computation_status_cache: dict[tuple[str, str], str | None] = {}


def get_raw_co_asset_id(raw_asset_name: str) -> str | None:
    """Look up the Code Ocean UUID for a raw asset by exact name. Cached."""
    if raw_asset_name in _co_raw_id_cache:
        return _co_raw_id_cache[raw_asset_name]
    co = _get_co_client()
    if co is None:
        return None
    try:
        results = co.data_assets.search_data_assets(
            DataAssetSearchParams(query=raw_asset_name, limit=5)
        )
        asset = next(
            (a for a in results.results if a.name == raw_asset_name), None
        )
        result: str | None = asset.id if asset else None
    except Exception as e:
        logger.warning("CO raw asset lookup failed for %s: %s", raw_asset_name, e)
        result = None
    _co_raw_id_cache[raw_asset_name] = result
    return result


def get_co_computation_status(
    raw_asset_co_id: str,
    pipeline_capsule_id: str,
    session_ts: float,
) -> str | None:
    """
    Scan the pipeline capsule's computation history for one that used
    raw_asset_co_id as input.

    Returns:
        'failed'  — computation found, exit_code != 0 or no results
        'running' — computation found, still in progress
        None      — no matching computation found (not yet triggered)

    Results are cached by (raw_asset_co_id, pipeline_capsule_id).
    None is not cached so we retry on the next table load.
    """
    cache_key = (raw_asset_co_id, pipeline_capsule_id)
    if cache_key in _co_computation_status_cache:
        return _co_computation_status_cache[cache_key]
    co = _get_co_client()
    if co is None:
        return None
    window_start = session_ts - 86400        # 1 day before session
    window_end = session_ts + 4 * 86400     # 4 days after (trigger delay + run)
    result: str | None = None
    try:
        for comp in co.capsules.list_computations(pipeline_capsule_id):
            if comp.created < window_start:
                break  # list is newest-first; gone past the window
            if comp.created > window_end:
                continue
            input_ids = {da.id for da in (comp.data_assets or [])}
            if raw_asset_co_id not in input_ids:
                continue
            if comp.state.value in ("running", "initializing"):
                result = "running"
            elif comp.exit_code != 0 or not comp.has_results:
                result = "failed"
            break
    except Exception as e:
        logger.warning("CO computation status lookup failed: %s", e)
    if result is not None:
        _co_computation_status_cache[cache_key] = result
    return result


pn.extension("tabulator", "modal")

# ---------------------------------------------------------------------------
# Watchdog log integration  (eng-logtools:8080)
# ---------------------------------------------------------------------------

_WATCHDOG_URL = "http://eng-logtools:8080/dstest"
_watchdog_cache: dict[str, tuple[float, dict[str, list]]] = {}
_WATCHDOG_TTL = 300  # 5 minutes


def _query_watchdog_dstest(message_filter: str, length: int = 2000) -> list:
    """POST to the eng-logtools DataTables endpoint. Returns list of row arrays."""
    cols = ["date", "source", "channel", "version", "level", "location", "message", "count"]
    body: dict[str, str] = {
        "draw": "1", "start": "0", "length": str(length),
        "search[value]": "", "search[regex]": "false",
        "order[0][column]": "0", "order[0][dir]": "desc",
    }
    for i, name in enumerate(cols):
        body[f"columns[{i}][data]"] = str(i)
        body[f"columns[{i}][name]"] = name
        body[f"columns[{i}][searchable]"] = "true"
        body[f"columns[{i}][orderable]"] = "true"
        body[f"columns[{i}][search][regex]"] = "true"
        if name == "channel":
            body[f"columns[{i}][search][value]"] = "watchdog"
        elif name == "message":
            body[f"columns[{i}][search][value]"] = message_filter
        else:
            body[f"columns[{i}][search][value]"] = ""
    try:
        r = req.post(
            _WATCHDOG_URL, data=body,
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=10,
        )
        return r.json().get("data", [])
    except Exception as e:
        logger.warning("Watchdog query failed: %s", e)
        return []


def fetch_watchdog_events(date_from, date_to) -> dict[str, list[dict]]:
    """
    Fetch watchdog log events for sessions whose names contain dates in
    [date_from, date_to].  Returns {sname: [event_dict, ...]} newest-first.
    Cached for _WATCHDOG_TTL seconds.
    """
    import re as _re
    import time as _time

    cache_key = f"{date_from}|{date_to}"
    cached = _watchdog_cache.get(cache_key)
    if cached and (_time.time() - cached[0]) < _WATCHDOG_TTL:
        return cached[1]

    # Build a regex that matches any YYYY-MM-DD in the date range.
    dates: list[str] = []
    d = date_from
    while d <= date_to:
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    date_regex = "|".join(dates)

    rows = _query_watchdog_dstest(message_filter=date_regex)

    events_by_session: dict[str, list[dict]] = {}
    for row in rows:
        msg = row[6] if len(row) > 6 else ""
        m = _re.search(r"name,\s*([^\s,][^,]*)", msg)
        if not m:
            continue
        raw_name = m.group(1).strip()
        sname = get_session_name(raw_name)
        if not sname:
            continue
        # Normalize T/Z timestamp format: '841302_2026-03-17T202227Z'
        #   → '841302_2026-03-17_20-22-27' to match DTS/DocDB session keys.
        tz_m = _re.match(r"^(\d+_\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})(\d{2})Z$", sname)
        if tz_m:
            sname = f"{tz_m.group(1)}_{tz_m.group(2)}-{tz_m.group(3)}-{tz_m.group(4)}"
        action_m = _re.match(r"(Action|Error),\s*([^,]+)", msg)
        event = {
            "datetime": row[0] if row else "",
            "source": row[1] if len(row) > 1 else "",
            "action": action_m.group(2).strip() if action_m else msg[:50],
            "message": msg,
        }
        events_by_session.setdefault(sname, []).append(event)

    _watchdog_cache[cache_key] = (_time.time(), events_by_session)
    return events_by_session


def watchdog_cell(events: list[dict]) -> str:
    """Format the Watchdog column cell HTML."""
    if not events:
        return "⬜"
    latest = events[0]  # newest-first
    rig = latest["source"].split("/")[0].strip()
    action = latest["action"]
    icon = "❌" if action.lower().startswith("error") else "✅"
    return (
        f'<span style="cursor:pointer;white-space:nowrap">'
        f"{icon} {rig}</span>"
    )


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
# Rig-side manifest detection
#
# Alex Piet's cron job (AllenNeuralDynamics/behavior_communication) SSHs into
# every behavior rig at 6am and captures a Windows `dir` listing of two folders:
#   manifest/          — sessions staged for the watchdog, not yet picked up
#   manifest_complete/ — sessions the watchdog has processed (submitted to DTS)
#
# The results are written as {RIG}.txt and {RIG}_complete.txt to MANIFEST_DIR.
# We read these files to surface sessions that never made it to the DTS.
# ---------------------------------------------------------------------------

AIND_LOGS_DIR = (
    "/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs"
)
MANIFEST_DIR = os.path.join(AIND_LOGS_DIR, "watchdog_manifests")

# Matches a file-entry line in a Windows `dir` listing, e.g.:
#   03/18/2026  09:35 AM     764 manifest_behavior_841859_2026-03-18_09-35-42.yml
_MANIFEST_LINE_RE = re.compile(
    r"^\s*\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2} [AP]M\s+[\d,]+\s+(manifest_\S+\.yml)\s*$"
)

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
            {"label": "Behavior Metadata Record", "modalities": {"behavior"},
             "co_pipeline_capsule_id": "da8785b1-1597-41c6-af30-5844f52d4947"},
            {"label": "FIB Metadata Record",      "modalities": {"fib", "fiber"},
             "co_pipeline_capsule_id": "9f8af19f-d107-488d-a3c1-a1f9db29401f"},
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
        # Enable rig-side manifest detection: reads Alex Piet's daily manifest snapshots
        # from MANIFEST_DIR to surface sessions that never reached the DTS.
        "use_manifests": True,
        "derived_columns": [
            {
                "label": "Derived Asset Metadata",
                "modalities": {"behavior", "fib", "fiber", "behavior-videos"},
                "co_pipeline_capsule_id": "250cf9b5-f438-4d31-9bbb-ba29dab47d56",
                "co_log_col": "CO Pipeline Log",
                "co_asset_col": "CO Derived Asset",
            },
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


def _co_log_col_name(derived_label: str) -> str:
    """'Behavior Metadata Record' → 'Behavior CO Log', etc."""
    return f"{derived_label.split()[0]} CO Log"


def _col_co_log_name(col: dict) -> str:
    """Return CO log column name, respecting optional 'co_log_col' override."""
    return col.get("co_log_col") or _co_log_col_name(col["label"])


def _col_co_asset_name(col: dict) -> str:
    """Return CO derived asset link column name, respecting optional 'co_asset_col' override."""
    return col.get("co_asset_col") or f"CO Derived {col['label'].split()[0]} Asset"


def co_log_cell(co_url: str | None) -> str:
    """Render a Code Ocean log cell based on the URL lookup result."""
    if co_url == "pending":
        return "⏳ pending"
    if co_url:
        return (
            f'<a href="{co_url}" target="_blank" rel="noopener noreferrer" '
            f'style="color:#1a73e8;text-decoration:underline">🔗 view log</a>'
        )
    return "⬜"


def _log_modal_html(log_text: str) -> str:
    """Render pipeline log text with a copy-to-clipboard button for the modal."""
    # Escape for HTML display and for embedding in a JS template literal.
    displayed = _html.escape(log_text)
    js_text = (
        log_text
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("${", "\\${")
    )
    return f"""
<div style="display:flex;flex-direction:column;height:100%;padding:8px;box-sizing:border-box">
  <div style="margin-bottom:8px;flex-shrink:0">
    <button
      style="padding:4px 12px;cursor:pointer;font-size:13px"
      onclick="
        navigator.clipboard.writeText(`{js_text}`)
          .then(() => {{
            this.textContent = '✅ Copied!';
            setTimeout(() => {{ this.textContent = '📋 Copy to clipboard'; }}, 2000);
          }})
          .catch(() => {{ this.textContent = '❌ Copy failed'; }});
      ">📋 Copy to clipboard</button>
  </div>
  <pre style="flex:1;overflow:auto;white-space:pre-wrap;word-wrap:break-word;
              background:#f8f8f8;padding:8px;font-size:12px;margin:0;
              border:1px solid #ddd;border-radius:4px">{displayed}</pre>
</div>
"""


def co_asset_link_cell(asset_id: str | None, asset_name: str) -> str:
    """Render a Code Ocean data-asset folder link."""
    if asset_id and asset_name:
        url = f"{_CO_DOMAIN}/data-assets/{asset_id}/{asset_name}/data"
        return (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            f'style="color:#1a73e8;text-decoration:underline">🔗 view data</a>'
        )
    return "⬜"


def find_gui_log_path(rig: str, session_name: str) -> str | None:
    """
    Find the GUI acquisition log file for a session on a given rig, or None.

    GUI logs live at {AIND_LOGS_DIR}/{rig}_gui_log/ and are named:
        {RIG}-{BOX}_gui_log_{YYYY-MM-DD}_{HH-MM-SS}.txt

    The filename timestamp is the GUI *launch* time, which is always before
    the session timestamp.  We find all logs on the session date, parse their
    timestamps, and return the one with the latest start time that is still
    at or before the session timestamp (i.e. the GUI that was running when
    the session was saved).
    """
    import glob as _glob
    from datetime import datetime as _dt
    parts = session_name.split("_")
    if len(parts) < 3:
        return None
    date_str, time_str = parts[1], parts[2]
    pattern = os.path.join(AIND_LOGS_DIR, f"{rig}_gui_log", f"*{date_str}*.txt")
    matches = _glob.glob(pattern)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    # Parse the timestamp from each filename and pick the closest one before
    # the session timestamp.
    try:
        session_ts = _dt.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H-%M-%S")
    except ValueError:
        return matches[0]
    candidates: list[tuple] = []
    for path in matches:
        fname = os.path.basename(path)
        try:
            ts_str = fname.replace(".txt", "").split("_gui_log_")[-1]
            ts = _dt.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")
            candidates.append((ts, path))
        except (ValueError, IndexError):
            continue
    if not candidates:
        return matches[0]
    before = [(ts, p) for ts, p in candidates if ts <= session_ts]
    if before:
        return max(before, key=lambda x: x[0])[1]
    # All logs are after session time — return the earliest
    return min(candidates, key=lambda x: x[0])[1]


def gui_log_cell(path: str | None) -> str:
    """Render the Rig Log column cell — clickable if a GUI log file was found."""
    if path:
        return '<span style="cursor:pointer;color:#1a73e8;text-decoration:underline">📋 view log</span>'
    return "⬜"


def rig_log_cell(manifest_entry: dict | None) -> str:
    """
    Render the Rig Log column cell based on rig-side manifest status.

    manifest_entry comes from load_manifest_sessions() and has keys:
        status:       "complete" — manifest processed by watchdog (submitted to DTS)
                      "pending"  — manifest staged on rig, not yet picked up
        rig:          rig hostname (e.g. "W10DT714027")
        session_raw:  original asset name from the manifest filename
    """
    if manifest_entry is None:
        return "⬜"
    status = manifest_entry.get("status", "")
    rig = manifest_entry.get("rig", "")
    if status == "complete":
        return (
            f'<span title="Manifest processed by watchdog on {rig}">'
            f"✅ {rig}</span>"
        )
    if status == "pending":
        return (
            f'<span style="color:#a60" '
            f'title="Manifest staged on {rig}, awaiting watchdog pickup">'
            f"⏳ {rig}</span>"
        )
    return "⬜"


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
        "acquisition.acquisition_start_time": 1,
        "session.session_start_time": 1,
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
        "acquisition.acquisition_start_time": 1,
        "session.session_start_time": 1,
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
        "acquisition.acquisition_start_time": 1,
        "session.session_start_time": 1,
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
# Rig manifest loader
# ---------------------------------------------------------------------------

@pn.cache(ttl=TTL_HOUR)
def load_manifest_sessions() -> dict[str, dict]:
    """
    Parse all per-rig manifest listing files from MANIFEST_DIR and return a
    dict mapping canonical session name → manifest metadata.

    Return value: {session_name: {"rig": str, "status": str, "session_raw": str}}
        status "complete" — manifest was in manifest_complete/ (watchdog processed it)
        status "pending"  — manifest was in manifest/ (staged, not yet picked up)
        session_raw       — full asset name from the manifest filename, e.g.
                            "behavior_822683_2026-03-18_09-35-42"

    Files are Windows `dir` listings written by Alex Piet's 6am cron job:
        {RIG}.txt          → manifest/ (pending)
        {RIG}_complete.txt → manifest_complete/ (complete)

    "complete" takes precedence if the same session appears in both.
    Cached for 1 hour since files are only refreshed once daily.
    """
    sessions: dict[str, dict] = {}
    try:
        filenames = os.listdir(MANIFEST_DIR)
    except OSError as e:
        logger.warning("Manifest directory not accessible (%s): %s", MANIFEST_DIR, e)
        return sessions

    for filename in filenames:
        if not filename.endswith(".txt"):
            continue
        if filename == "processed.txt":
            continue
        if filename.endswith("_complete.txt"):
            rig = filename[: -len("_complete.txt")]
            status = "complete"
        else:
            rig = filename[: -len(".txt")]
            status = "pending"

        filepath = os.path.join(MANIFEST_DIR, filename)
        try:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = _MANIFEST_LINE_RE.match(line.rstrip("\n"))
                    if not m:
                        continue
                    manifest_fname = m.group(1)
                    # e.g. "manifest_behavior_822683_2026-03-18_09-35-42.yml"
                    # → session_raw = "behavior_822683_2026-03-18_09-35-42"
                    session_raw = manifest_fname[len("manifest_") : -len(".yml")]
                    sname = get_session_name(session_raw)
                    if not sname:
                        continue
                    # "complete" takes precedence if the session appears in both files
                    if sname not in sessions or status == "complete":
                        sessions[sname] = {
                            "rig": rig,
                            "status": status,
                            "session_raw": session_raw,
                        }
        except OSError as e:
            logger.warning("Could not read manifest file %s: %s", filepath, e)

    logger.info("Loaded %d sessions from rig manifests", len(sessions))
    return sessions


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
    manifest_sessions: dict | None = None,
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

    # Parallel CO lookup for all derived assets — populates _co_url_cache and
    # _co_derived_id_cache so both log-link and data-link columns are ready.
    all_derived_names = {
        r["name"]
        for records in derived_by_session.values()
        for r in records
    }
    all_raw_names = {r["name"] for r in raw_by_session.values() if r.get("name")}
    if _get_co_client() is not None:
        if all_derived_names:
            uncached = [n for n in all_derived_names if n not in _co_url_cache]
            if uncached:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    list(executor.map(get_co_output_url, uncached))
        if all_raw_names:
            uncached_raw = [n for n in all_raw_names if n not in _co_raw_id_cache]
            if uncached_raw:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    list(executor.map(get_raw_co_asset_id, uncached_raw))

    # Filter both DTS and DocDB sessions by the date the session was actually
    # acquired (not the DTS execution_date, which reflects when the job ran and
    # can include old sessions that were retried or reprocessed recently).
    #
    # For DTS sessions: use the date encoded in the session name.
    # For DocDB-only sessions: prefer acquisition.acquisition_start_time (ground
    # truth), falling back to the session name date when not present.
    def _acquisition_date(r: dict) -> datetime | None:
        # V2 schema: acquisition.acquisition_start_time
        # V1 schema: session.session_start_time
        # Fallback: date encoded in the asset name
        for ts_str in (
            (r.get("acquisition") or {}).get("acquisition_start_time", ""),
            (r.get("session") or {}).get("session_start_time", ""),
        ):
            if ts_str:
                try:
                    d = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
        return session_date(get_session_name(r.get("name", "")))

    dts_in_range: set[str] = set()
    for sname in dts_by_name:
        d = session_date(sname)
        if d is not None and date_from <= d <= date_to:
            dts_in_range.add(sname)

    docdb_only: set[str] = set()
    for sname, raw_rec in raw_by_session.items():
        if sname not in dts_by_name:
            d = _acquisition_date(raw_rec)
            if d is not None and date_from <= d <= date_to:
                docdb_only.add(sname)

    all_sessions = dts_in_range | docdb_only

    # Fetch watchdog events for the date range (cached, ~0.4s on first call).
    try:
        watchdog_events = fetch_watchdog_events(date_from, date_to)
    except Exception as e:
        logger.warning("Watchdog fetch failed: %s", e)
        watchdog_events = {}

    # Sessions with DTS success but no derived asset: mark for on-demand click lookup.
    # The {(sname, col_label): session_ts} map is used at render time to decide
    # whether to show "⏳ running" (recent) vs "⚠️ check log?" (pipeline should be done).
    import time as _time
    pending_session_ts: dict[tuple[str, str], float] = {}
    _now_ts = _time.time()
    for sname in all_sessions:
        dts_job = dts_by_name.get(sname)
        if not dts_job or dts_job.get("job_state") != "success":
            continue
        raw = raw_by_session.get(sname)
        if not raw:
            continue
        derived = derived_by_session.get(sname, [])
        job_type = dts_job.get("job_type")
        expected = job_types[job_type]["expected_pipelines"] if job_type else None
        sdt = session_datetime(sname)
        session_ts = sdt.timestamp() if sdt else 0.0
        for col in derived_columns:
            if not col.get("co_pipeline_capsule_id"):
                continue
            if expected is not None and not col["modalities"] & expected:
                continue
            if any(col["modalities"] & set(get_modalities(r)) for r in derived):
                continue
            pending_session_ts[(sname, col["label"])] = session_ts

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
        wd_events = watchdog_events.get(sname, [])
        manifest_entry = manifest_sessions.get(sname) if manifest_sessions else None
        rig = manifest_entry["rig"] if manifest_entry else ""
        gui_log_path = find_gui_log_path(rig, sname) if rig else None
        row: dict = {
            "Subject": subject_id,
            "Session Date": dt_str,
            "Modalities": modalities,
            "Session Name": display_name,
            "Rig Log": gui_log_cell(gui_log_path),
            "_rig_log_path": gui_log_path or "",
            "Rig Manifest": rig_log_cell(manifest_entry),
            "_rig_manifest_rig": rig,
            "Watchdog": watchdog_cell(wd_events),
            "_watchdog_sname": sname,
            "DTS Upload": dts_html,
            "_dts_url": dts_url,
            "Raw Asset Metadata": asset_cell(raw_name or None),
            "_name_Raw Asset Metadata": raw_name,
            "CO Raw Asset": co_asset_link_cell(_co_raw_id_cache.get(raw_name), raw_name),
        }
        for col in derived_columns:
            co_log_col = _col_co_log_name(col)
            co_asset_col = _col_co_asset_name(col)
            if expected is not None and not col["modalities"] & expected:
                row[co_log_col] = "—"
                row[co_asset_col] = "—"
                row[col["label"]] = "—"
                row[f"_name_{col['label']}"] = ""
                row[f"_comp_id_{col['label']}"] = ""
            else:
                record = next(
                    (r for r in derived if col["modalities"] & set(get_modalities(r))),
                    None,
                )
                name = record["name"] if record else ""

                # CO log cell
                comp_id_key = f"_comp_id_{col['label']}"
                if name:
                    row[co_log_col] = co_log_cell(_co_url_cache.get(name))
                    row[comp_id_key] = ""
                else:
                    session_ts = pending_session_ts.get((sname, col["label"]))
                    if session_ts is not None:
                        age_hours = (_now_ts - session_ts) / 3600
                        if age_hours > 8:
                            row[co_log_col] = (
                                '<span style="cursor:pointer;color:#a60">'
                                "⚠️ check log?</span>"
                            )
                        else:
                            row[co_log_col] = (
                                '<span style="cursor:pointer">⏳ running</span>'
                            )
                        row[comp_id_key] = ""
                    else:
                        row[co_log_col] = "⬜"
                        row[comp_id_key] = ""

                # CO derived asset data-folder link
                row[co_asset_col] = co_asset_link_cell(
                    _co_derived_id_cache.get(name), name
                )

                row[col["label"]] = asset_cell(name or None)
                row[f"_name_{col['label']}"] = name

        rows.append(row)

    # Add rows for sessions found in rig manifests but absent from both DTS and DocDB.
    # These are sessions where the watchdog processed the manifest (or it's still pending)
    # but the session never appeared in DTS — the "fell through the cracks" case.
    if manifest_sessions:
        for sname, mentry in sorted(
            manifest_sessions.items(),
            key=lambda kv: session_datetime(kv[0]) or _epoch,
            reverse=True,
        ):
            if sname in all_sessions:
                continue  # already represented via DTS or DocDB
            d = session_date(sname)
            if d is None or not (date_from <= d <= date_to):
                continue  # outside the selected date window
            subject_id, dt_str = parse_session_name(sname)
            within_14d = d >= cutoff_14d
            wd_events = watchdog_events.get(sname, [])
            dts_html, _ = dts_cell(None, within_14d)
            display_name = mentry.get("session_raw", sname)
            mrig = mentry.get("rig", "")
            m_gui_log_path = find_gui_log_path(mrig, sname) if mrig else None
            manifest_row: dict = {
                "Subject": subject_id,
                "Session Date": dt_str,
                "Modalities": "",
                "Session Name": display_name,
                "Rig Log": gui_log_cell(m_gui_log_path),
                "_rig_log_path": m_gui_log_path or "",
                "Rig Manifest": rig_log_cell(mentry),
                "_rig_manifest_rig": mrig,
                "Watchdog": watchdog_cell(wd_events),
                "_watchdog_sname": sname,
                "DTS Upload": dts_html,
                "_dts_url": "",
                "Raw Asset Metadata": "⬜",
                "_name_Raw Asset Metadata": "",
                "CO Raw Asset": "⬜",
            }
            for col in derived_columns:
                co_log_col = _col_co_log_name(col)
                co_asset_col = _col_co_asset_name(col)
                manifest_row[co_log_col] = "⬜"
                manifest_row[col["label"]] = "⬜"
                manifest_row[co_asset_col] = "⬜"
                manifest_row[f"_name_{col['label']}"] = ""
                manifest_row[f"_comp_id_{col['label']}"] = ""
            rows.append(manifest_row)

    fixed_cols = ["Subject", "Session Date", "Modalities", "Session Name",
                  "Rig Log", "Rig Manifest", "Watchdog", "DTS Upload", "Raw Asset Metadata", "CO Raw Asset"]
    derived_col_list = []
    for c in derived_columns:
        derived_col_list.append(_col_co_log_name(c))
        derived_col_list.append(c["label"])
        derived_col_list.append(_col_co_asset_name(c))
    hidden_cols = (
        ["_dts_url", "_watchdog_sname", "_name_Raw Asset Metadata",
         "_rig_log_path", "_rig_manifest_rig"]
        + [f"_name_{c['label']}" for c in derived_columns]
        + [f"_comp_id_{c['label']}" for c in derived_columns]
    )
    return (
        pd.DataFrame(rows, columns=fixed_cols + derived_col_list + hidden_cols),
        watchdog_events,
    )


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
            base_status = (
                f"⚠️ **DTS unavailable** _(requires AIND network or VPN)_: {dts_error}\n\n"
                f"Showing {len(records_in_range)} DocDB records only."
            )
        else:
            n_dts = sum(1 for j in dts_jobs if j.get("job_type") in job_type_names)
            base_status = (
                f"**{n_dts} DTS jobs** · "
                f"**{len(records_in_range)} DocDB records** · "
                f"{date_from.date()} → {date_to.date()} · "
                f"_DTS cache: 5min, DocDB cache: 1hr_"
            )

        if subject:
            dts_jobs = [j for j in dts_jobs if subject in j.get("name", "")]
            all_records = [r for r in all_records if subject in r.get("name", "")]

        # Rig-side manifest sessions (only for projects that opt in)
        manifest_sessions: dict = {}
        if cfg.get("use_manifests"):
            try:
                manifest_sessions = load_manifest_sessions()
                if subject:
                    manifest_sessions = {
                        k: v for k, v in manifest_sessions.items() if subject in k
                    }
            except Exception as e:
                logger.warning("Manifest session load failed: %s", e)

        status_md.object = base_status

        try:
            df, watchdog_events = build_session_table(
                dts_jobs, all_records, job_types, derived_columns, date_from, date_to,
                manifest_sessions=manifest_sessions,
            )
        except Exception as exc:
            import traceback
            logger.error("build_session_table failed: %s", traceback.format_exc())
            status_md.object = f"❌ Table build failed: {exc}"
            load_button.disabled = False
            return

        if df.empty:
            table_col[:] = [pn.pane.Markdown("_No sessions found for the selected filters._")]
        else:
            co_log_col_names = {_col_co_log_name(c) for c in derived_columns}
            # Map CO log column → hidden comp_id column for failed log lookups.
            co_log_comp_id_col = {
                _col_co_log_name(c): f"_comp_id_{c['label']}"
                for c in derived_columns
            }
            # Map CO log column → capsule_id for on-demand pending lookups.
            co_log_capsule_col = {
                _col_co_log_name(c): c.get("co_pipeline_capsule_id", "")
                for c in derived_columns
            }
            # Map CO log column → hidden asset name column.
            # Non-empty name means the cell has a <a href> link — browser handles it.
            co_log_name_col = {
                _col_co_log_name(c): f"_name_{c['label']}"
                for c in derived_columns
            }
            html_cols = (
                ["Rig Log", "Rig Manifest", "Watchdog", "DTS Upload",
                 "Raw Asset Metadata", "CO Raw Asset"]
                + list(co_log_col_names)
                + [c["label"] for c in derived_columns]
                + [_col_co_asset_name(c) for c in derived_columns]
            )
            hidden_cols = (
                ["_dts_url", "_watchdog_sname", "_name_Raw Asset Metadata",
                 "_rig_log_path", "_rig_manifest_rig"]
                + [f"_name_{c['label']}" for c in derived_columns]
                + [f"_comp_id_{c['label']}" for c in derived_columns]
            )
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
                    .tabulator-col-title { white-space: normal !important; word-wrap: break-word; }
                """],
            )

            async def on_cell_click(
                event, _df=df, _co_log_cols=co_log_col_names,
                _wd_events=watchdog_events,
                _co_log_comp_id=co_log_comp_id_col,
                _co_log_capsule=co_log_capsule_col,
                _co_log_name=co_log_name_col,
            ):
                import asyncio
                row = _df.iloc[event.row]
                col = event.column

                if col in _co_log_cols:
                    # If the cell has a CO link (<a href>), the browser already
                    # handles the click — skip the modal entirely.
                    name_col = _co_log_name.get(col, "")
                    if name_col and str(row.get(name_col, "")):
                        return

                    # For failed/pending computations open the pipeline log in modal.
                    comp_id_col = _co_log_comp_id.get(col, "")
                    if not comp_id_col or comp_id_col not in _df.columns:
                        return
                    comp_id = str(row.get(comp_id_col, ""))

                    if not comp_id:
                        # ⚠️ / ⏳ cell — show modal immediately then search.
                        capsule_id = _co_log_capsule.get(col, "")
                        sname = str(row.get("_watchdog_sname", ""))
                        raw_name = str(row.get("_name_Raw Asset Metadata", ""))
                        if not capsule_id or not sname:
                            return
                        sdt = session_datetime(sname)
                        if sdt is None:
                            return
                        session_ts = sdt.timestamp()
                        co = _get_co_client()
                        if co is None:
                            return

                        # Show modal immediately so the user gets feedback.
                        _modal_body[:] = [pn.pane.Markdown(
                            "🔍 Searching for pipeline log…",
                            styles={"padding": "16px"},
                        )]
                        _inspector_modal.show()

                        def _find_comp() -> tuple[str, str]:
                            """Sync search; runs in thread pool.

                            Returns (comp_id, message) where comp_id is empty on
                            failure and message explains the outcome.

                            Strategy:
                            1. Collect all comps in the session time window.
                            2. If none → pipeline was never triggered.
                            3. Filter to failed comps.
                            4. If none (only successes) → pipeline ran but DocDB
                               hasn't picked up the derived asset yet.
                            5. For each failed comp, fetch log and search for the
                               subject ID — reliable even when data_assets is None.
                            6. Only fall back to timing if exactly one candidate.
                            """
                            win_lo = session_ts - 3600
                            win_hi = session_ts + 86400
                            subject_id, _ = parse_session_name(sname)
                            all_window: list = []
                            failed: list = []
                            try:
                                for comp in co.capsules.list_computations(capsule_id):
                                    if not (win_lo <= comp.created <= win_hi):
                                        continue
                                    all_window.append(comp)
                                    is_success = (
                                        comp.state.value == "completed"
                                        and comp.exit_code == 0
                                        and comp.has_results is not False
                                    )
                                    is_running = comp.state.value in (
                                        "running", "initializing", "finalizing"
                                    )
                                    if not is_success and not is_running:
                                        failed.append(comp)
                            except Exception as exc:
                                logger.warning("list_computations failed: %s", exc)
                                return "", "Error searching for pipeline log."

                            if not all_window:
                                return "", (
                                    "No pipeline run found for this session. "
                                    "The pipeline may not have been triggered."
                                )
                            if not failed:
                                return "", (
                                    "The pipeline ran successfully for sessions in "
                                    "this time window, but the derived asset has not "
                                    "yet been registered in DocDB."
                                )

                            # Search failed comp logs for the subject ID.
                            if subject_id:
                                for comp in failed:
                                    try:
                                        urls = co.computations.get_result_file_urls(
                                            comp.id, "output"
                                        )
                                        r = req.get(urls.view_url, timeout=15)
                                        if r.ok and subject_id in r.text:
                                            return comp.id, ""
                                    except Exception as exc:
                                        logger.warning(
                                            "Log fetch for %s failed: %s",
                                            comp.id, exc,
                                        )

                            # Unambiguous timing fallback.
                            if len(failed) == 1:
                                return failed[0].id, ""

                            return "", (
                                f"Found {len(failed)} failed pipeline run(s) in this "
                                "time window, but none reference this session. "
                                "The pipeline may not have been triggered for this session."
                            )

                        loop = asyncio.get_event_loop()
                        comp_id, msg = await loop.run_in_executor(None, _find_comp)
                        if not comp_id:
                            _modal_body[:] = [pn.pane.Markdown(
                                msg or "No pipeline log found for this session.",
                                styles={"padding": "16px"},
                            )]
                            return
                    else:
                        # ❌ comp_id already known — show loading modal now.
                        _modal_body[:] = [pn.pane.Markdown(
                            "🔍 Loading pipeline log…",
                            styles={"padding": "16px"},
                        )]
                        _inspector_modal.show()

                    co = _get_co_client()
                    if co is None:
                        return

                    def _fetch_log_text():
                        urls = co.computations.get_result_file_urls(comp_id, "output")
                        r = req.get(urls.view_url, timeout=30)
                        r.raise_for_status()
                        return r.text

                    loop = asyncio.get_event_loop()
                    try:
                        log_text = await loop.run_in_executor(None, _fetch_log_text)
                        _modal_body[:] = [pn.pane.HTML(
                            _log_modal_html(log_text),
                            sizing_mode="stretch_both",
                        )]
                    except Exception as exc:
                        logger.warning("Failed to get computation log: %s", exc)
                        _modal_body[:] = [pn.pane.Markdown(
                            f"Failed to load pipeline log: {exc}",
                            styles={"padding": "16px"},
                        )]
                    return

                if col == "Rig Log":
                    path = str(row.get("_rig_log_path", ""))
                    if not path:
                        return
                    sname = str(row.get("_watchdog_sname", ""))
                    _modal_body[:] = [pn.pane.Markdown(
                        "🔍 Loading acquisition log…", styles={"padding": "16px"}
                    )]
                    _inspector_modal.show()

                    def _load_gui_log(_path=path):
                        try:
                            with open(_path, encoding="utf-8", errors="replace") as f:
                                return f.read()
                        except OSError as e:
                            return f"Could not read log: {e}"

                    loop = asyncio.get_event_loop()
                    log_text = await loop.run_in_executor(None, _load_gui_log)
                    _modal_body[:] = [pn.pane.HTML(
                        _log_modal_html(log_text), sizing_mode="stretch_both"
                    )]
                    return

                if col == "Rig Manifest":
                    rig = str(row.get("_rig_manifest_rig", ""))
                    if not rig:
                        return
                    sname = str(row.get("_watchdog_sname", ""))
                    watchdog_log_path = os.path.join(
                        AIND_LOGS_DIR, "watchdog_logs", f"{rig}_aind-watchdog-service.log"
                    )
                    _modal_body[:] = [pn.pane.Markdown(
                        f"🔍 Loading watchdog log for **{rig}**…", styles={"padding": "16px"}
                    )]
                    _inspector_modal.show()

                    def _load_watchdog_log(_path=watchdog_log_path, _sname=sname, _rig=rig):
                        if not os.path.exists(_path):
                            return (
                                f"No watchdog service log found for rig {_rig}.\n\n"
                                f"Log would be at: {_path}"
                            )
                        try:
                            with open(_path, encoding="utf-8", errors="replace") as f:
                                lines = f.readlines()
                        except OSError as e:
                            return f"Could not read watchdog log: {e}"
                        # Search for lines referencing this session by subject+date
                        # (more specific than date alone; avoids matching all sessions that day)
                        parts = _sname.split("_")
                        terms = [_sname]
                        if len(parts) >= 2:
                            terms.append(f"{parts[0]}_{parts[1]}")  # subject_date
                        matching = [l for l in lines if any(t in l for t in terms)]
                        if not matching:
                            return (
                                f"No watchdog log entries found for {_sname}.\n\n"
                                f"The rig may not have been running the watchdog service "
                                f"when this session was uploaded, or the log has been rotated."
                            )
                        return "".join(matching)

                    loop = asyncio.get_event_loop()
                    log_text = await loop.run_in_executor(None, _load_watchdog_log)
                    _modal_body[:] = [pn.pane.HTML(
                        _log_modal_html(log_text), sizing_mode="stretch_both"
                    )]
                    return

                if col == "Watchdog":
                    sname = str(row.get("_watchdog_sname", ""))
                    events = _wd_events.get(sname, [])
                    if not events:
                        return
                    lines = [
                        f"**{e['datetime']}** &nbsp; {e['source'].split('/')[0].strip()} &nbsp; "
                        f"{'❌' if e['action'].lower().startswith('error') else '✅'} {e['action']}"
                        for e in reversed(events)
                    ]
                    _modal_body[:] = [pn.pane.Markdown(
                        f"**Watchdog events: {sname}**\n\n" + "\n\n".join(lines),
                        sizing_mode="stretch_width",
                        styles={"overflow": "auto", "max-height": "88vh", "padding": "8px"},
                    )]
                    _inspector_modal.show()
                    return

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

                def _fetch_record():
                    return get_full_record(asset_name)

                loop = asyncio.get_event_loop()
                record = await loop.run_in_executor(None, _fetch_record)
                json_pane.object = (
                    sort_record_for_display(json.loads(json.dumps(record, default=str)))
                    if record else {"error": f"Record not found: {asset_name}"}
                )

            tab.on_click(on_cell_click)
            table_col[:] = [tab]
        load_button.disabled = False

    load_button.on_click(on_load)

    def _on_input_change(_event=None):
        if table_col.objects:  # only clear if results are currently shown
            table_col[:] = []
            status_md.object = ""

    for widget in (project_select, date_from_picker, date_to_picker, subject_input):
        widget.param.watch(_on_input_change, "value")

    if pn.state.location:
        # Keep sync so URL stays updated when the user changes widgets and re-runs.
        pn.state.location.sync(project_select, {"value": "project"})
        pn.state.location.sync(subject_input, {"value": "subject"})
        pn.state.location.sync(date_from_picker, {"value": "date_from"})
        pn.state.location.sync(date_to_picker, {"value": "date_to"})

        # Pre-fill fields from URL params when they arrive from the browser.
        # pn.state.onload fires before location data is available, so we watch
        # location.search.  We only apply params once (on first non-empty search
        # string) and never auto-trigger a load — the user must click Load Sessions.
        _params_applied = [False]

        def _on_search_arrive(event):
            if _params_applied[0] or not event.new:
                return
            _params_applied[0] = True
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
        "⏳ running/queued/pending &nbsp;&nbsp; "
        "⬜ not yet reached &nbsp;&nbsp; "
        "— not applicable &nbsp;&nbsp; "
        "_Rig Log opens the GUI acquisition log; Rig Manifest shows watchdog status and opens the watchdog service log. DTS and asset cells open an inline viewer._",
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
