"""
Session Status Viewer — Panel frontend for aind-session-utils.

This module is pure presentation: it imports ``aind_session_utils`` for all
data access and delegates every query to ``fetch_and_build_sessions``.  No
DocDB/DTS/CO client calls, no caching logic, and no session name parsing live
here — those concerns belong to the library.

DATA FLOW:
    1. User selects platform, date range, and subject filter, then clicks Load.
    2. ``fetch_and_build_sessions`` queries DTS, rig manifests, and DocDB,
       assembles ``SessionResult`` objects (using the parquet store for
       settled sessions), and returns them along with a status summary.
    3. ``build_session_table`` converts the results to an HTML-cell DataFrame
       for the Tabulator widget.
    4. Cell clicks open a modal with log text, JSON metadata, or watchdog events.

LIMITATIONS:
    - DTS API enforces a 14-day lookback window; older sessions show "N/A".
    - Rig manifests require the AIND on-prem network share to be mounted.
    - Code Ocean features require CODEOCEAN_DOMAIN and CODEOCEAN_API_TOKEN.

ADDING A PLATFORM:
    Create a YAML file in ``aind_session_utils/platform_configs/``.
    See ``aind_session_utils/config.py`` for the schema.

URL PARAMETERS:
    - platform:  pre-select platform (e.g. ?platform=Dynamic+Foraging)
    - subject:   pre-fill subject ID filter (e.g. ?subject=822683)
    - date_from: pre-fill start date (e.g. ?date_from=2026-03-04)
    - date_to:   pre-fill end date   (e.g. ?date_to=2026-03-11)
"""

import json
import logging
import os
import threading
import time as _time_mod
from datetime import datetime, timedelta, timezone
import html as _html

import pandas as pd
import panel as pn


from dotenv import load_dotenv

from aind_session_utils import (
    SessionResult,
    SessionTableRow,
    PipelineColumnStatus,
    get_pipeline_log,
    get_full_record,
    AIND_LOGS_DIR,
    fetch_and_build_sessions,
    build_session_rows,
    ParquetSessionStore,
    list_platform_configs,
    to_viewer_config,
    get_pipeline_column_names,
)

load_dotenv()  # picks up .env in the working directory (or any parent)

logger = logging.getLogger("session_viewer")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_h)

# Platform configs loaded from YAML files in aind_session_utils/platform_configs/.
# To add a platform, create a new YAML file there.
# To override a bundled config, set AIND_SESSION_USER_CONFIG_DIR to a directory
# containing a YAML file with the same 'name' field.
PLATFORM_CONFIG: dict[str, dict] = {
    cfg["name"]: to_viewer_config(cfg)
    for cfg in list_platform_configs()
}

_session_store = ParquetSessionStore()

pn.extension("tabulator", "modal")

# ---------------------------------------------------------------------------
# JSON display helper
# ---------------------------------------------------------------------------

def sort_record_for_display(obj: object) -> object:
    """Recursively reorder a dict so scalar values appear before nested ones.

    Alphabetical within each tier.  Makes the JSON inspector modal easier
    to scan — leaf metadata floats to the top at every nesting level.
    """
    if not isinstance(obj, dict):
        return obj
    flat = {k: obj[k] for k in sorted(obj) if not isinstance(obj[k], (dict, list))}
    nested = {k: sort_record_for_display(obj[k]) for k in sorted(obj) if isinstance(obj[k], (dict, list))}
    return {**flat, **nested}


# ---------------------------------------------------------------------------
# HTML cell helpers (all return strings for Tabulator HTML formatters)
# ---------------------------------------------------------------------------

_DTS_ICONS = {
    "success": "✅",
    "failed": "❌",
    "running": "⏳",
    "queued": "⏳",
    "up_for_retry": "⏳",
}


def dts_cell(status: str | None, url: str, within_14_days: bool) -> tuple[str, str]:
    """Render the DTS Upload cell.

    Args:
        status:         DTS job state string, or None if no job exists.
        url:            Pre-built Airflow task-detail URL, or empty string.
        within_14_days: False for sessions beyond the DTS lookback window.

    Returns:
        ``(html, url)`` — ``url`` is non-empty only when a drill-down link
        is available (so the click handler knows to open it).
    """
    if not within_14_days:
        return '<span style="color:#888;">N/A (&gt;14 days)</span>', ""
    if status is None:
        return "⬜", ""
    icon = _DTS_ICONS.get(status, "❓")
    if url:
        return (
            f'<span style="cursor:pointer;color:#1a73e8;text-decoration:underline">'
            f"{icon} view tasks/logs</span>",
            url,
        )
    return f"{icon} {status}", ""


def asset_cell(name: str | None) -> str:
    """Render a DocDB asset cell — clickable when an asset name is known."""
    if not name:
        return "⬜"
    return '<span style="cursor:pointer;color:#1a73e8;text-decoration:underline">✅ view metadata</span>'


def co_log_cell(co_url: str | None) -> str:
    """Render a Code Ocean derived-asset log cell.

    Args:
        co_url: CO output URL (success), ``'pending'`` (in progress), or None.
    """
    if co_url == "pending":
        return "⏳"
    if co_url:
        return '<span style="cursor:pointer" title="View pipeline log">✅ view log</span>'
    return ""


def co_asset_link_cell(url: str) -> str:
    """Render a Code Ocean data-asset folder link from a pre-built URL.

    Args:
        url: Pre-built CO data-asset URL, or empty string.
    """
    if url:
        return (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            f'style="color:#1a73e8;text-decoration:underline">🔗 view data</a>'
        )
    return "⬜"


def _pipeline_log_cell(ps: "PipelineColumnStatus") -> str:
    """Render the CO pipeline log cell from a PipelineColumnStatus."""
    if ps.status == "not_applicable":
        return "—"
    if ps.status == "complete":
        return co_log_cell(ps.co_log_url)
    if ps.status == "pending":
        return "⏳"
    if ps.status == "failed":
        return (
            '<span style="cursor:pointer" '
            'title="Pipeline ran but produced no output — click to check log">'
            "❌ view log</span>"
        )
    # never_triggered or not in CO
    return '<span style="color:#aaa" title="No pipeline run found">⊘</span>'


def gui_log_cell(path: str | None) -> str:
    """Render the acquisition GUI log cell — clickable when a log file was found.

    Args:
        path: Filesystem path to the GUI log file, or None.
    """
    if path:
        return '<span style="cursor:pointer;color:#1a73e8;text-decoration:underline">📋 view log</span>'
    return "⬜"


def rig_log_cell(manifest_status: str | None, manifest_rig: str) -> str:
    """Render the Rig Manifest cell based on watchdog manifest status.

    Args:
        manifest_status: ``'complete'``, ``'pending'``, or None.
        manifest_rig:    Hostname of the rig that staged the manifest.
    """
    if manifest_status is None:
        return "⬜"
    rig = manifest_rig
    if manifest_status == "complete":
        return (
            f'<span title="Manifest processed by watchdog on {rig}">'
            f"✅ {rig}</span>"
        )
    if manifest_status == "pending":
        return (
            f'<span style="color:#a60" '
            f'title="Manifest staged on {rig}, awaiting watchdog pickup">'
            f"⏳ {rig}</span>"
        )
    return "⬜"


def watchdog_cell(summary: str | None, has_error: bool) -> str:
    """Render the Watchdog cell from pre-computed summary fields.

    Args:
        summary:   Rig name from the latest watchdog event, or None.
        has_error: True if the latest event action starts with "error".
    """
    if summary is None:
        return "⬜"
    icon = "❌" if has_error else "✅"
    return f'<span style="cursor:pointer;white-space:nowrap">{icon} {summary}</span>'


def _log_modal_pane(log_text: str) -> pn.viewable.Viewable:
    """Build a Panel pane with a copy button and scrollable pre-formatted log.

    Args:
        log_text: Raw log text to display.
    """
    displayed = _html.escape(log_text)
    html = f"""
<div style="display:flex;flex-direction:column;height:100%;padding:8px;box-sizing:border-box">
  <div style="margin-bottom:8px;flex-shrink:0">
    <button style="padding:4px 12px;cursor:pointer;font-size:13px"
      onclick="var pre=this.parentElement.nextElementSibling;
               var r=document.createRange();
               r.selectNodeContents(pre);
               var s=window.getSelection();
               s.removeAllRanges();
               s.addRange(r);
               document.execCommand('copy');
               s.removeAllRanges();
               var b=this;
               b.textContent='Copied!';
               setTimeout(function(){{b.textContent='Copy to Clipboard';}},2000);">
      Copy to Clipboard</button>
  </div>
  <pre style="flex:1;overflow:auto;white-space:pre-wrap;word-wrap:break-word;
              background:#f8f8f8;padding:8px;font-size:12px;margin:0;
              border:1px solid #ddd;border-radius:4px">{displayed}</pre>
</div>"""
    return pn.pane.HTML(html, sizing_mode="stretch_both")


# Column name helper — all three column names derived from pipeline_descriptor.

def _col_names(col: dict):
    """Return (log_col, asset_col, derived_col) for a pipeline config dict."""
    return get_pipeline_column_names(col)


# ---------------------------------------------------------------------------
# Table builder
# ---------------------------------------------------------------------------

def build_session_table(
    rows: list[SessionTableRow],
    derived_columns: list[dict],
) -> pd.DataFrame:
    """Convert ``SessionTableRow`` objects to an HTML-cell DataFrame for Tabulator.

    Pure presentation — wraps structured data in HTML.  Each field is rendered
    by one of the ``*_cell()`` helpers.  Hidden ``_``-prefixed columns carry
    raw values for click handlers and filters.

    Args:
        rows:            List of ``SessionTableRow`` objects from
                         ``build_session_rows()``.
        derived_columns: Pipeline column configs from the platform config.

    Returns:
        DataFrame with HTML-formatted cells and hidden metadata columns,
        ordered: fixed columns → derived triples → hidden columns.
    """
    table_rows = []
    for row in rows:
        raw_name = row.raw_asset_name or ""
        dts_html, dts_url = dts_cell(row.dts_status, row.dts_url, row.within_14d)
        html_row: dict = {
            "Subject": row.subject_id,
            "Session Date": row.session_datetime_display,
            "Modalities": ", ".join(row.modalities),
            "Session Name": row.display_name,
            "Rig Log": gui_log_cell(row.rig_log_path),
            "_rig_log_path": row.rig_log_path or "",
            "Rig Manifest": rig_log_cell(row.manifest_status, row.manifest_rig),
            "_rig_manifest_rig": row.manifest_rig,
            "Watchdog": watchdog_cell(row.watchdog_summary, row.watchdog_has_error),
            "_watchdog_sname": row.session_name,
            "DTS Upload": dts_html,
            "_dts_url": dts_url,
            "Raw Asset Metadata": asset_cell(raw_name or None),
            "_name_Raw Asset Metadata": raw_name,
            "CO Raw Asset": co_asset_link_cell(row.raw_co_data_url),
        }
        for i, col in enumerate(derived_columns):
            cn = _col_names(col)
            ps = row.pipeline_statuses[i]
            if ps.status == "not_applicable":
                html_row[cn.log_col] = "—"
                html_row[cn.asset_col] = "—"
                html_row[cn.derived_col] = "—"
                html_row[f"_name_{cn.derived_col}"] = ""
            else:
                html_row[cn.log_col] = _pipeline_log_cell(ps)
                html_row[cn.asset_col] = co_asset_link_cell(ps.co_data_url)
                html_row[cn.derived_col] = asset_cell(ps.derived_asset_name or None)
                html_row[f"_name_{cn.derived_col}"] = ps.derived_asset_name

        html_row["_completeness_status"] = row.completeness_status
        table_rows.append(html_row)

    fixed_cols = [
        "Subject", "Session Date", "Modalities", "Session Name",
        "Rig Log", "Rig Manifest", "Watchdog", "DTS Upload",
        "Raw Asset Metadata", "CO Raw Asset",
    ]
    derived_col_list = []
    for c in derived_columns:
        cn = _col_names(c)
        derived_col_list.append(cn.log_col)
        derived_col_list.append(cn.derived_col)
        derived_col_list.append(cn.asset_col)
    hidden_cols = (
        ["_dts_url", "_watchdog_sname", "_name_Raw Asset Metadata",
         "_rig_log_path", "_rig_manifest_rig", "_completeness_status"]
        + [f"_name_{_col_names(c).derived_col}" for c in derived_columns]
    )

    df = pd.DataFrame(table_rows, columns=fixed_cols + derived_col_list + hidden_cols)
    return df


# ---------------------------------------------------------------------------
# Panel app
# ---------------------------------------------------------------------------

def build_panel_app():
    today = datetime.now(tz=timezone.utc).date()
    default_from = today - timedelta(days=7)

    platform_select = pn.widgets.Select(
        name="",
        options=list(PLATFORM_CONFIG.keys()),
        width=380,
    )
    date_from_picker = pn.widgets.DatePicker(name="", value=default_from, width=130)
    date_to_picker = pn.widgets.DatePicker(name="", value=today, width=130)
    subject_input = pn.widgets.TextInput(
        placeholder="e.g. 822683",
        width=160,
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

        # Capture all widget values on the main thread before launching background work.
        platform_name = platform_select.value
        cfg = PLATFORM_CONFIG[platform_name]
        derived_columns: list[dict] = cfg["derived_columns"]
        no_derived_expected: frozenset[str] = cfg.get("no_derived_expected", frozenset())
        subject = subject_input.value.strip()

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

        load_button.disabled = True
        table_col[:] = []

        # --- Progress ticker ---
        _t0 = _time_mod.time()
        _step = ["⏳ Starting…"]

        def _tick():
            elapsed = _time_mod.time() - _t0
            status_md.object = f"{_step[0]} _{elapsed:.0f}s_"

        _ticker = pn.state.add_periodic_callback(_tick, 500)

        def _set_step(msg: str) -> None:
            """Update the step label immediately (ticker keeps elapsed refreshed)."""
            _step[0] = msg
            pn.state.execute(_tick)

        def _stop_ticker_and_set(msg: str) -> None:
            _ticker.stop()
            status_md.object = msg

        # --- Background load ---
        def _do_load():
            import traceback

            try:
                sessions, base_status = fetch_and_build_sessions(
                    platform_config=cfg,
                    date_from=date_from,
                    date_to=date_to,
                    subject=subject,
                    store=_session_store,
                    no_derived_expected=no_derived_expected,
                    step_callback=_set_step,
                )

                _set_step(f"⏳ Building table ({len(sessions)} sessions)…")
                table_rows = build_session_rows(sessions, derived_columns, no_derived_expected)
                watchdog_events = {
                    tr.session_name: list(tr.watchdog_events) for tr in table_rows
                }

                try:
                    df = build_session_table(table_rows, derived_columns)
                except Exception as exc:
                    logger.error("build_session_table failed: %s", traceback.format_exc())
                    pn.state.execute(lambda: _stop_ticker_and_set(f"❌ Table build failed: {exc}"))
                    pn.state.execute(lambda: setattr(load_button, "disabled", False))
                    return

                # Hand off to main thread for UI construction.
                pn.state.execute(lambda: _finish(df, base_status, watchdog_events))

            except Exception as exc:
                logger.error("on_load thread failed: %s", traceback.format_exc())
                pn.state.execute(lambda: _stop_ticker_and_set(f"❌ Load failed: {exc}"))
                pn.state.execute(lambda: setattr(load_button, "disabled", False))

        # --- Main-thread finish (UI construction — runs on the main thread) ---
        def _finish(df, base_status, watchdog_events):
            _ticker.stop()
            if df.empty:
                table_col[:] = [pn.pane.Markdown("_No sessions found for the selected filters._")]
                status_md.object = base_status
                load_button.disabled = False
                return
            co_log_col_names = {_col_names(c).log_col for c in derived_columns}
            # Map CO log column → capsule_id for on-demand log fetch.
            co_log_capsule_col = {
                _col_names(c).log_col: c.get("co_pipeline_capsule_id", "")
                for c in derived_columns
            }
            # Map CO log column → hidden asset name column.
            # Non-empty name means the cell has a <a href> link — browser handles it.
            co_log_name_col = {
                _col_names(c).log_col: f"_name_{_col_names(c).derived_col}"
                for c in derived_columns
            }
            html_cols = (
                ["Rig Log", "Rig Manifest", "Watchdog", "DTS Upload",
                 "Raw Asset Metadata", "CO Raw Asset"]
                + list(co_log_col_names)
                + [_col_names(c).derived_col for c in derived_columns]
                + [_col_names(c).asset_col for c in derived_columns]
            )
            hidden_cols = (
                ["_dts_url", "_watchdog_sname", "_name_Raw Asset Metadata",
                 "_rig_log_path", "_rig_manifest_rig", "_completeness_status"]
                + [f"_name_{_col_names(c).derived_col}" for c in derived_columns]
            )
            # Rename multi-word visible columns to use <br> so headers wrap to
            # data-content width instead of header-text width.
            _hidden_set = set(hidden_cols)
            col_rename = {
                c: "<br>".join(c.split())
                for c in df.columns
                if c not in _hidden_set and " " in c and not c.startswith("_")
            }
            col_unrename = {v: k for k, v in col_rename.items()}
            html_cols = [col_rename.get(c, c) for c in html_cols]
            co_log_col_names = {col_rename.get(c, c) for c in co_log_col_names}
            co_log_capsule_col = {col_rename.get(k, k): v for k, v in co_log_capsule_col.items()}
            co_log_name_col = {col_rename.get(k, k): v for k, v in co_log_name_col.items()}
            _rig_log_col = col_rename.get("Rig Log", "Rig Log")
            _rig_manifest_col = col_rename.get("Rig Manifest", "Rig Manifest")
            _watchdog_col = col_rename.get("Watchdog", "Watchdog")
            _dts_upload_col = col_rename.get("DTS Upload", "DTS Upload")
            df_display = df.rename(columns=col_rename)
            # Store full df (renamed) for the orphan toggle to slice from.
            _full_df_holder[0] = df_display
            # Apply orphan filter in Python before building the Tabulator — more reliable
            # than Tabulator's client-side boolean filter which has serialization issues.
            display_df = df_display[df_display["_completeness_status"] != "complete"] if orphan_toggle.value else df_display
            tab = pn.widgets.Tabulator(
                display_df,
                formatters={c: {"type": "html"} for c in html_cols if c in display_df.columns},
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
                    .tabulator-col-content { flex: 1 !important; display: flex !important; flex-direction: column !important; }
                    .tabulator-col-title-holder { flex: 1 !important; display: flex !important; align-items: center !important; }
                """],
            )
            _tab_holder[0] = tab

            async def on_cell_click(
                event, _co_log_cols=co_log_col_names,
                _wd_events=watchdog_events,
                _co_log_capsule=co_log_capsule_col,
                _co_log_name=co_log_name_col,
                _col_unrename=col_unrename,
                _rig_log_col=_rig_log_col,
                _rig_manifest_col=_rig_manifest_col,
                _watchdog_col=_watchdog_col,
                _dts_upload_col=_dts_upload_col,
            ):
                import asyncio
                row = tab.value.iloc[event.row]
                col = event.column

                if col in _co_log_cols:
                    # All CO log cells (successful, pending, failed) open in modal.
                    name_col = _co_log_name.get(col, "")
                    has_derived = bool(name_col and str(row.get(name_col, "")))

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
                        _modal_body[:] = [_log_modal_pane(log_text)]
                    return

                if col == _rig_log_col:
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
                    _modal_body[:] = [_log_modal_pane(log_text)]
                    return

                if col == _rig_manifest_col:
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
                    _modal_body[:] = [_log_modal_pane(log_text)]
                    return

                if col == _watchdog_col:
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

                if col == _dts_upload_col:
                    url = str(row.get("_dts_url", ""))
                    if not url:
                        return
                    _modal_body[:] = [pn.pane.HTML(
                        f'<iframe src="{url}" style="width:100%;height:100%;min-height:85vh;border:none;flex:1;"></iframe>',
                        sizing_mode="stretch_both",
                    )]
                    _inspector_modal.show()
                    return

                name_col = f"_name_{_col_unrename.get(col, col)}"
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
            status_md.object = base_status
            load_button.disabled = False

        threading.Thread(target=_do_load, daemon=True).start()

    load_button.on_click(on_load)

    def _on_input_change(_event=None):
        if table_col.objects:  # only clear if results are currently shown
            table_col[:] = []
            status_md.object = ""

    for widget in (platform_select, date_from_picker, date_to_picker, subject_input):
        widget.param.watch(_on_input_change, "value")

    if pn.state.location:
        # Keep sync so URL stays updated when the user changes widgets and re-runs.
        pn.state.location.sync(platform_select, {"value": "platform"})
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
            if "platform" in params:
                platform = params["platform"][0]
                if platform in PLATFORM_CONFIG:
                    platform_select.value = platform
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

    controls = pn.Row(
        pn.Column("**Platform**", platform_select),
        pn.Spacer(width=12),
        pn.Column("**Date range**", pn.Row("From", date_from_picker, pn.Spacer(width=6), "To", date_to_picker)),
        pn.Spacer(width=12),
        pn.Column("**Subject ID (optional)**", subject_input),
        pn.Spacer(width=12),
        pn.Column("&nbsp;", load_button),
        pn.Spacer(width=12),
        pn.Column("&nbsp;", orphan_toggle),
        align="start",
    )

    return pn.Column(
        header,
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
