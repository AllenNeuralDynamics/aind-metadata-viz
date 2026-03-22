"""Session data model and joining logic.

``build_sessions`` takes already-queried DTS jobs, DocDB records, and
optional manifest sessions, then joins them by canonical session name and
enriches each session with CO, watchdog, and rig-log data.  It returns a
list of ``SessionResult`` objects sorted newest-first.

``build_session_table`` in ``session_viewer.py`` consumes these objects and
converts them to an HTML-cell DataFrame for Tabulator.
"""

from __future__ import annotations

import logging
import time as _time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from aind_session_utils.naming import (
    _DERIVED_MARKERS,
    get_modalities,
    get_session_name,
    parse_session_name,
    session_date,
    session_datetime,
)
from aind_session_utils.sources.codeocean import (
    _co_derived_id_cache,
    _co_raw_id_cache,
    _co_url_cache,
    _get_co_client,
    get_co_output_url,
    get_raw_co_asset_id,
)
from aind_session_utils.sources.dts import DTS_BASE_URL, DTS_MAX_LOOKBACK_DAYS
from aind_session_utils.sources.rig_logs import find_rig_log
from aind_session_utils.sources.watchdog import fetch_watchdog_events

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DerivedAssetInfo:
    """One derived asset found for a session."""

    asset_name: str
    docdb_id: Optional[str]
    modalities: frozenset[str]
    co_asset_id: Optional[str]   # Code Ocean data-asset UUID
    co_log_url: Optional[str]    # CO output log URL, "pending", or None


@dataclass(frozen=True)
class SessionResult:
    """Everything found about a session across all available sources."""

    # Identity
    session_name: str
    subject_id: str
    acquisition_datetime: Optional[datetime]
    raw_modalities: frozenset[str]
    display_name: str             # actual asset name shown in the table

    # Rig-side
    rig_log_path: Optional[str]
    manifest_entry: Optional[dict]  # {status, rig, session_raw} or None
    watchdog_events: tuple[dict, ...]

    # Upload
    dts_status: Optional[str]    # "success"|"failed"|"running"|"queued"|None
    dts_job_url: str              # pre-built Airflow URL, or ""
    within_14d: bool

    # Raw asset
    raw_asset_name: Optional[str]
    raw_docdb_id: Optional[str]
    raw_co_asset_id: Optional[str]

    # Expected pipelines (from job_types config → which derived columns apply)
    # None means no DTS job → expected is unknown → show ⬜ for all columns.
    expected_pipelines: Optional[frozenset[str]]

    # Derived assets
    derived_assets: tuple[DerivedAssetInfo, ...]


def _best_datetime(raw_record: dict, sname: str) -> Optional[datetime]:
    """Return the best available acquisition datetime for a raw record.

    Prefers the DocDB start-time fields (ground truth), falls back to the
    date/time encoded in the session name.
    """
    for ts_str in (
        (raw_record.get("acquisition") or {}).get("acquisition_start_time", ""),
        (raw_record.get("session") or {}).get("session_start_time", ""),
    ):
        if ts_str:
            try:
                d = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return session_datetime(sname)


def _build_dts_url(job: dict) -> str:
    """Build the Airflow task-detail URL for a DTS job dict."""
    dag_run_id = job.get("job_id", "")
    dag = job.get("dag_id", "transform_and_upload_v2")
    if dag_run_id:
        return (
            f"{DTS_BASE_URL}/job_tasks_table"
            f"?dag_id={quote(str(dag))}&dag_run_id={quote(str(dag_run_id))}"
        )
    return ""


def build_sessions(
    dts_jobs: list[dict],
    all_docdb_records: list[dict],
    job_types: dict[str, dict],
    date_from: datetime,
    date_to: datetime,
    manifest_sessions: Optional[dict] = None,
) -> list[SessionResult]:
    """Join DTS jobs, DocDB records, watchdog events, and rig data.

    Args:
        dts_jobs:          DTS job dicts already queried for the date range.
        all_docdb_records: DocDB records already fetched for the project.
        job_types:         {job_type_name: {"expected_pipelines": set[str]}}
                           from the project config.
        date_from:         Start of date range (UTC, inclusive).
        date_to:           End of date range (UTC, inclusive).
        manifest_sessions: Optional {sname: {status, rig, session_raw}} from
                           rig-side manifest files.  When provided, sessions
                           found only in manifests (not DTS or DocDB) are
                           included as extra rows.

    Returns:
        List of SessionResult, sorted newest-first.
    """
    t0 = _time.time()

    def _log(msg: str) -> None:
        logger.info("build_sessions [%.2fs] %s", _time.time() - t0, msg)

    now_utc = datetime.now(tz=timezone.utc)
    cutoff_14d = now_utc - timedelta(days=DTS_MAX_LOOKBACK_DAYS)
    _epoch = datetime.min.replace(tzinfo=timezone.utc)

    # ------------------------------------------------------------------ #
    # 1. Index DTS jobs by canonical session name.                         #
    # ------------------------------------------------------------------ #
    dts_by_name: dict[str, dict] = {
        get_session_name(j["name"]): j
        for j in dts_jobs
        if j.get("job_type") in job_types
    }

    # ------------------------------------------------------------------ #
    # 2. Index DocDB records by session name, split raw vs derived.        #
    # ------------------------------------------------------------------ #
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

    _log(
        f"indexed {len(raw_by_session)} raw + {len(derived_by_session)} "
        f"derived sessions from DocDB"
    )

    # ------------------------------------------------------------------ #
    # 3. Determine the session set (DTS in range + DocDB-only in range).   #
    # ------------------------------------------------------------------ #
    dts_in_range: set[str] = set()
    for sname in dts_by_name:
        d = session_date(sname)
        if d is not None and date_from <= d <= date_to:
            dts_in_range.add(sname)

    docdb_only: set[str] = set()
    for sname, raw_rec in raw_by_session.items():
        if sname not in dts_by_name:
            d = _best_datetime(raw_rec, sname)
            if d is not None and date_from <= d <= date_to:
                docdb_only.add(sname)

    all_sessions = dts_in_range | docdb_only
    _log(f"session sets: {len(dts_in_range)} DTS + {len(docdb_only)} DocDB-only")

    # ------------------------------------------------------------------ #
    # 4. Parallel CO lookup (pre-populate caches for all sessions).        #
    # ------------------------------------------------------------------ #
    all_derived_names = {
        r["name"]
        for sname in all_sessions
        for r in derived_by_session.get(sname, [])
        if r.get("name")
    }
    all_raw_names = {
        raw_by_session[sname]["name"]
        for sname in all_sessions
        if sname in raw_by_session and raw_by_session[sname].get("name")
    }
    if _get_co_client() is not None:
        uncached_derived = [n for n in all_derived_names if n not in _co_url_cache]
        uncached_raw = [n for n in all_raw_names if n not in _co_raw_id_cache]
        if uncached_derived or uncached_raw:
            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = (
                    [executor.submit(get_co_output_url, n) for n in uncached_derived]
                    + [executor.submit(get_raw_co_asset_id, n) for n in uncached_raw]
                )
                for f in futures:
                    f.result()
        _log(
            f"CO lookups done ({len(uncached_derived)} derived, "
            f"{len(uncached_raw)} raw)"
        )

    # ------------------------------------------------------------------ #
    # 5. Fetch watchdog events (cached ~0.4s on first call).               #
    # ------------------------------------------------------------------ #
    try:
        watchdog_events_dict = fetch_watchdog_events(date_from, date_to)
    except Exception as exc:
        logger.warning("Watchdog fetch failed: %s", exc)
        watchdog_events_dict = {}
    _log("watchdog events fetched")

    # ------------------------------------------------------------------ #
    # 6. Build SessionResult objects for DTS + DocDB sessions.             #
    # ------------------------------------------------------------------ #
    results: list[SessionResult] = []

    for sname in sorted(
        all_sessions,
        key=lambda s: session_datetime(s) or _epoch,
        reverse=True,
    ):
        dts_job = dts_by_name.get(sname)
        raw = raw_by_session.get(sname)
        derived_recs = derived_by_session.get(sname, [])

        # Subject ID: prefer DocDB, fall back to name parsing.
        subject_id, _ = parse_session_name(sname)
        if raw:
            subject_id = (
                (raw.get("subject") or {}).get("subject_id") or subject_id
            )

        # Best acquisition datetime.
        acq_dt = _best_datetime(raw, sname) if raw else session_datetime(sname)

        # within_14d: used for the DTS cell (shows "N/A" if too old for DTS).
        d = session_date(sname)
        within_14d = d is None or d >= cutoff_14d

        # DTS info.
        dts_status = dts_job.get("job_state") if dts_job else None
        dts_url = _build_dts_url(dts_job) if dts_job else ""

        # Expected pipelines for this job type (None = unknown).
        job_type = dts_job.get("job_type") if dts_job else None
        expected = (
            frozenset(job_types[job_type]["expected_pipelines"])
            if job_type and job_type in job_types
            else None
        )

        # Raw asset info.
        raw_name = raw["name"] if raw else None
        raw_docdb_id = raw.get("_id") if raw else None
        raw_co_id = _co_raw_id_cache.get(raw_name) if raw_name else None

        # Display name: prefer raw DocDB name, fall back to DTS name, then sname.
        display_name = (
            raw_name
            if raw_name
            else (dts_job["name"] if dts_job else sname)
        )

        # Raw modalities.
        raw_mods = frozenset(get_modalities(raw)) if raw else frozenset()

        # Rig-side: manifest entry and log path.
        manifest_entry = (
            manifest_sessions.get(sname) if manifest_sessions else None
        )
        rig = manifest_entry.get("rig", "") if manifest_entry else ""
        rig_log_path = find_rig_log(rig, sname) if rig else None

        # Watchdog events.
        wd_events = tuple(watchdog_events_dict.get(sname, []))

        # Derived assets.
        derived_assets = tuple(
            DerivedAssetInfo(
                asset_name=r["name"],
                docdb_id=r.get("_id"),
                modalities=frozenset(get_modalities(r)),
                co_asset_id=_co_derived_id_cache.get(r["name"]),
                co_log_url=_co_url_cache.get(r["name"]),
            )
            for r in derived_recs
            if r.get("name")
        )

        results.append(SessionResult(
            session_name=sname,
            subject_id=subject_id,
            acquisition_datetime=acq_dt,
            raw_modalities=raw_mods,
            display_name=display_name,
            rig_log_path=rig_log_path,
            manifest_entry=manifest_entry,
            watchdog_events=wd_events,
            dts_status=dts_status,
            dts_job_url=dts_url,
            within_14d=within_14d,
            raw_asset_name=raw_name,
            raw_docdb_id=raw_docdb_id,
            raw_co_asset_id=raw_co_id,
            expected_pipelines=expected,
            derived_assets=derived_assets,
        ))

    # ------------------------------------------------------------------ #
    # 7. Add manifest-only sessions (not in DTS or DocDB).                 #
    # ------------------------------------------------------------------ #
    if manifest_sessions:
        for sname, mentry in sorted(
            manifest_sessions.items(),
            key=lambda kv: session_datetime(kv[0]) or _epoch,
            reverse=True,
        ):
            if sname in all_sessions:
                continue
            d = session_date(sname)
            if d is None or not (date_from <= d <= date_to):
                continue

            subject_id, _ = parse_session_name(sname)
            within_14d = d >= cutoff_14d
            mrig = mentry.get("rig", "")
            m_rig_log = find_rig_log(mrig, sname) if mrig else None
            wd_events = tuple(watchdog_events_dict.get(sname, []))

            results.append(SessionResult(
                session_name=sname,
                subject_id=subject_id,
                acquisition_datetime=session_datetime(sname),
                raw_modalities=frozenset(),
                display_name=mentry.get("session_raw", sname),
                rig_log_path=m_rig_log,
                manifest_entry=mentry,
                watchdog_events=wd_events,
                dts_status=None,
                dts_job_url="",
                within_14d=within_14d,
                raw_asset_name=None,
                raw_docdb_id=None,
                raw_co_asset_id=None,
                expected_pipelines=None,
                derived_assets=(),
            ))

    _log(f"done: {len(results)} sessions total")
    return results
