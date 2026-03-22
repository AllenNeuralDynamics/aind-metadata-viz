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
from datetime import datetime, timedelta, timezone
import html as _html

import requests as req
import pandas as pd
import panel as pn


from dotenv import load_dotenv

from aind_session_utils.naming import (
    get_session_name, parse_session_name, session_date,
    session_datetime, get_modalities,
)
from aind_session_utils.sources.docdb import (
    get_project_records, get_raw_records_by_names,
    get_full_record, filter_records_by_date,
)
from aind_session_utils.sources.dts import (
    get_dts_jobs, DTS_MAX_LOOKBACK_DAYS, DTS_CACHE_TTL,
)
from aind_session_utils.sources.codeocean import (
    _get_co_client, _co_raw_id_cache,
    _get_run_id_for_asset, _update_co_run_cache, _CO_DOMAIN,
    get_pipeline_log,
)
from aind_session_utils.sources.manifests import (
    load_manifest_sessions, AIND_LOGS_DIR, MANIFEST_DIR, _MANIFEST_LINE_RE,
)
from aind_session_utils.config import list_project_configs, to_viewer_config
from aind_session_utils.session import SessionResult, build_sessions
from aind_session_utils.completeness import check_completeness

load_dotenv()  # picks up .env in the working directory (or any parent)

pn.extension("tabulator", "modal")


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

METADATA_PORTAL_BASE = "https://metadata-portal.allenneuraldynamics-test.org"

# Load project configs from YAML files in aind_session_utils/project_configs/.
# To add a project, create a new YAML file there.
# To override a bundled config, set AIND_SESSION_USER_CONFIG_DIR to a directory
# containing a YAML file with the same 'name' field.
PROJECT_CONFIG: dict[str, dict] = {
    cfg["name"]: to_viewer_config(cfg)
    for cfg in list_project_configs()
}

logger = logging.getLogger("session_viewer")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_h)

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


def dts_cell(status: str | None, url: str, within_14_days: bool) -> tuple[str, str]:
    """
    Render the DTS status cell as an HTML string, and return the DTS URL (or "").

    Returns (html, url) — url is non-empty only when a task drill-down is available.
    status and url are pre-computed by build_sessions() in session.py.
    """
    if not within_14_days:
        return '<span style="color:#888;">N/A (&gt;14 days)</span>', ""
    if status is None:
        return "⬜", ""
    icon = _DTS_ICONS.get(status, "❓")
    if url:
        html = f'<span style="cursor:pointer;color:#1a73e8;text-decoration:underline">{icon} view tasks/logs</span>'
        return html, url
    return f"{icon} {status}", ""


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
        # Clickable span — opens in modal (same UX as failed/pending logs).
        return '<span style="cursor:pointer;color:#1a73e8;text-decoration:underline">🔗 view log</span>'
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
# Table builder
# ---------------------------------------------------------------------------

def build_session_table(
    sessions: list[SessionResult],
    derived_columns: list[dict],
    no_derived_expected: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    """Convert SessionResult objects to a DataFrame with HTML cells.

    This is pure presentation.  It iterates the already-assembled SessionResult
    objects from build_sessions() and renders each field using the *_cell()
    functions.  No querying, no joining.
    """
    import time as _time
    _now_ts = _time.time()

    rows = []
    for sr in sessions:
        _, dt_str = parse_session_name(sr.session_name)
        raw_name = sr.raw_asset_name or ""
        dts_html, dts_url = dts_cell(sr.dts_status, sr.dts_job_url, sr.within_14d)
        completeness = check_completeness(sr, no_derived_expected)
        row: dict = {
            "Subject": sr.subject_id,
            "Session Date": dt_str,
            "Modalities": ", ".join(sorted(sr.raw_modalities)),
            "Session Name": sr.display_name,
            "Rig Log": gui_log_cell(sr.rig_log_path),
            "_rig_log_path": sr.rig_log_path or "",
            "Rig Manifest": rig_log_cell(sr.manifest_entry),
            "_rig_manifest_rig": (sr.manifest_entry or {}).get("rig", ""),
            "Watchdog": watchdog_cell(list(sr.watchdog_events)),
            "_watchdog_sname": sr.session_name,
            "DTS Upload": dts_html,
            "_dts_url": dts_url,
            "Raw Asset Metadata": asset_cell(raw_name or None),
            "_name_Raw Asset Metadata": raw_name,
            "CO Raw Asset": co_asset_link_cell(sr.raw_co_asset_id, raw_name),
        }
        for col in derived_columns:
            co_log_col = _col_co_log_name(col)
            co_asset_col = _col_co_asset_name(col)
            expected = sr.expected_pipelines
            col_mods = col["modalities"]
            # Determine whether this pipeline column applies to this session.
            # Prefer expected_pipelines (from DTS job type) for precision; fall
            # back to raw_modalities when there's no DTS job (e.g. >14 days).
            # If neither is known, leave it as ⬜ (unknown).
            if expected is not None:
                not_applicable = not col_mods & expected
            elif sr.raw_modalities:
                not_applicable = not col_mods & sr.raw_modalities
            else:
                not_applicable = False
            if not_applicable:
                # N/A: this session's modalities don't include this pipeline.
                row[co_log_col] = "—"
                row[co_asset_col] = "—"
                row[col["label"]] = "—"
                row[f"_name_{col['label']}"] = ""
                row[f"_comp_id_{col['label']}"] = ""
            else:
                # Find the matching derived asset for this column's modalities.
                da = next(
                    (d for d in sr.derived_assets if col["modalities"] & d.modalities),
                    None,
                )
                asset_name = da.asset_name if da else ""
                comp_id_key = f"_comp_id_{col['label']}"
                if asset_name:
                    row[co_log_col] = co_log_cell(da.co_log_url if da else None)
                    row[comp_id_key] = ""
                else:
                    # Show ⏳/⚠️ if the raw asset reached CO but no derived asset
                    # exists yet.  Use raw_co_asset_id (not dts_status) as the
                    # signal — DTS status is unavailable for sessions >14 days old
                    # or DocDB-only sessions, yet the pipeline may still have run.
                    is_pending = (
                        sr.raw_co_asset_id is not None
                        and bool(col.get("co_pipeline_capsule_id"))
                    )
                    if is_pending:
                        session_ts = (
                            sr.acquisition_datetime.timestamp()
                            if sr.acquisition_datetime
                            else 0.0
                        )
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

                row[co_asset_col] = co_asset_link_cell(
                    da.co_asset_id if da else None, asset_name
                )
                row[col["label"]] = asset_cell(asset_name or None)
                row[f"_name_{col['label']}"] = asset_name

        row["_completeness_status"] = completeness.status
        rows.append(row)

    fixed_cols = [
        "Subject", "Session Date", "Modalities", "Session Name",
        "Rig Log", "Rig Manifest", "Watchdog", "DTS Upload",
        "Raw Asset Metadata", "CO Raw Asset",
    ]
    derived_col_list = []
    for c in derived_columns:
        derived_col_list.append(_col_co_log_name(c))
        derived_col_list.append(c["label"])
        derived_col_list.append(_col_co_asset_name(c))
    hidden_cols = (
        ["_dts_url", "_watchdog_sname", "_name_Raw Asset Metadata",
         "_rig_log_path", "_rig_manifest_rig", "_completeness_status"]
        + [f"_name_{c['label']}" for c in derived_columns]
        + [f"_comp_id_{c['label']}" for c in derived_columns]
    )

    df = pd.DataFrame(rows, columns=fixed_cols + derived_col_list + hidden_cols)
    return df


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
    orphan_toggle = pn.widgets.Checkbox(
        name="Only show sessions missing derived asset",
        value=False,
    )
    status_md = pn.pane.Markdown("", sizing_mode="stretch_width")
    table_col = pn.Column(sizing_mode="stretch_width")

    # Holders so the orphan toggle callback can access the current tab and full df.
    _tab_holder: list = [None]
    _full_df_holder: list = [None]

    def _apply_orphan_filter(event):
        tab = _tab_holder[0]
        full_df = _full_df_holder[0]
        if tab is None or full_df is None:
            return
        tab.value = full_df[full_df["_completeness_status"] != "complete"] if event.new else full_df

    orphan_toggle.param.watch(_apply_orphan_filter, "value")

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
        derived_columns: list[dict] = cfg["derived_columns"]
        no_derived_expected: frozenset[str] = cfg.get("no_derived_expected", frozenset())

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

        # DTS — server-side, clamped to its 14-day lookback window.
        dts_cutoff = datetime.now(tz=timezone.utc) - timedelta(days=DTS_MAX_LOOKBACK_DAYS - 1)
        dts_from = max(date_from, dts_cutoff)
        dts_to = date_to
        dts_jobs, dts_error = get_dts_jobs(dts_from.isoformat(), dts_to.isoformat()) if dts_from <= dts_to else ([], None)

        # Rig-side manifest sessions (loaded before DocDB so their session names
        # can be included in the bootstrap project-name discovery below).
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

        # DocDB — query by project name.
        #
        # For projects with known project names, query directly.
        # For projects with no configured names (e.g. Dynamic Foraging, which
        # spans many PI-specific project names), bootstrap project-name discovery
        # from DTS job names AND manifest session names (manifest covers sessions
        # older than the 14-day DTS window, e.g. subjects whose first appearance
        # in DTS is recent but whose older sessions are in the manifest).
        try:
            bootstrap_modalities: frozenset[str] = frozenset()
            if not docdb_project_names:
                # Collect all session asset-names we know about: DTS jobs in the
                # 14-day window + manifest sessions in the selected date range.
                dts_names = tuple(
                    j["name"] for j in dts_jobs if j.get("job_type") in job_type_names
                )
                manifest_names = tuple(
                    mentry.get("session_raw", sname)
                    for sname, mentry in manifest_sessions.items()
                    if (d := session_date(sname)) is not None
                    and date_from <= d <= date_to
                )
                bootstrap_names = tuple(set(dts_names) | set(manifest_names))
                bootstrap_records = get_raw_records_by_names(bootstrap_names, docdb_versions)
                docdb_project_names = tuple(sorted({
                    r.get("data_description", {}).get("project_name")
                    for r in bootstrap_records
                    if r.get("data_description", {}).get("project_name")
                }))
                bootstrap_modalities = frozenset(
                    m for r in bootstrap_records for m in get_modalities(r)
                )
                logger.info(
                    "Discovered project names: %s, modalities: %s",
                    docdb_project_names, bootstrap_modalities,
                )

            all_records = get_project_records(docdb_project_names, docdb_versions)

            # If we bootstrapped project names, filter out records with unrelated
            # modalities (e.g. SmartSPIM sessions under the same project name).
            if bootstrap_modalities:
                all_records = [
                    r for r in all_records
                    if not get_modalities(r) or set(get_modalities(r)) & bootstrap_modalities
                ]
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

        status_md.object = base_status

        try:
            sessions = build_sessions(
                dts_jobs, all_records, job_types, date_from, date_to,
                manifest_sessions=manifest_sessions,
            )
            watchdog_events = {
                sr.session_name: list(sr.watchdog_events) for sr in sessions
            }

            # Warm the CO run cache in a background thread so ⚠️/⏳ cell clicks
            # are instant.  Mirrors the get_log_for_session.py caching strategy:
            # list_computations is slow but only called once; subsequent lookups
            # hit the in-memory/disk cache immediately.
            _pipeline_ids = {
                c["co_pipeline_capsule_id"]
                for c in derived_columns
                if c.get("co_pipeline_capsule_id")
            }
            if _pipeline_ids and _get_co_client() is not None:
                import threading
                def _warm_run_caches(_ids=_pipeline_ids):
                    for pid in _ids:
                        _update_co_run_cache(pid)
                threading.Thread(target=_warm_run_caches, daemon=True).start()

            df = build_session_table(sessions, derived_columns, no_derived_expected)
        except Exception as exc:
            import traceback
            logger.error("build_session_table failed: %s", traceback.format_exc())
            status_md.object = f"❌ Table build failed: {exc}"
            load_button.disabled = False
            return

        if df.empty:
            table_col[:] = [pn.pane.Markdown("_No sessions found for the selected filters._")]
        else:
            # Store full df for the orphan toggle to slice from.
            _full_df_holder[0] = df

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
                 "_rig_log_path", "_rig_manifest_rig", "_completeness_status"]
                + [f"_name_{c['label']}" for c in derived_columns]
                + [f"_comp_id_{c['label']}" for c in derived_columns]
            )
            # Apply orphan filter in Python before building the Tabulator — more reliable
            # than Tabulator's client-side boolean filter which has serialization issues.
            display_df = df[df["_completeness_status"] != "complete"] if orphan_toggle.value else df
            tab = pn.widgets.Tabulator(
                display_df,
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
            _tab_holder[0] = tab

            async def on_cell_click(
                event, _co_log_cols=co_log_col_names,
                _wd_events=watchdog_events,
                _co_log_comp_id=co_log_comp_id_col,
                _co_log_capsule=co_log_capsule_col,
                _co_log_name=co_log_name_col,
            ):
                import asyncio
                row = tab.value.iloc[event.row]
                col = event.column

                if col in _co_log_cols:
                    # All CO log cells (successful, pending, failed) open in modal.
                    name_col = _co_log_name.get(col, "")
                    has_derived = bool(name_col and str(row.get(name_col, "")))

                    comp_id_col = _co_log_comp_id.get(col, "")
                    if not comp_id_col or comp_id_col not in tab.value.columns:
                        return
                    comp_id = str(row.get(comp_id_col, ""))

                    capsule_id = _co_log_capsule.get(col, "")
                    raw_name = str(row.get("_name_Raw Asset Metadata", ""))
                    if not capsule_id or not raw_name:
                        return

                    loading_msg = (
                        "🔍 Loading pipeline log…"
                        if has_derived
                        else "🔍 Searching for pipeline log…"
                    )
                    _modal_body[:] = [pn.pane.Markdown(
                        loading_msg, styles={"padding": "16px"}
                    )]
                    _inspector_modal.show()

                    loop = asyncio.get_event_loop()
                    log_text, err = await loop.run_in_executor(
                        None, get_pipeline_log, raw_name, capsule_id
                    )
                    if log_text is None:
                        _modal_body[:] = [pn.pane.Markdown(
                            err, styles={"padding": "16px"}
                        )]
                    else:
                        _modal_body[:] = [pn.pane.HTML(
                            _log_modal_html(log_text), sizing_mode="stretch_both"
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
                if name_col not in tab.value.columns:
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
        pn.Spacer(width=20),
        pn.Column("&nbsp;", orphan_toggle),
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
