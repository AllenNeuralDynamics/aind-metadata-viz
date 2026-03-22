"""Persistent parquet-based session store.

Settled sessions (completeness status == "complete") are written to local
parquet files and returned on subsequent loads without re-querying DTS or
DocDB.  Unsettled sessions are always re-queried and re-saved.

Files (under AIND_SESSION_CACHE_DIR or ~/.cache/aind_session_utils/):
    sessions.parquet        — one row per session (PK: session_name)
    derived_assets.parquet  — one row per derived asset (FK: session_name)

All I/O is wrapped in try/except so a corrupt or missing store never breaks
the viewer — it just falls back to a full re-query.
"""

from __future__ import annotations

import logging
import os
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import pandas as pd

if TYPE_CHECKING:
    from aind_session_utils.session import SessionResult

logger = logging.getLogger(__name__)

_DEFAULT_STORE_DIR = Path.home() / ".cache" / "aind_session_utils"


def get_store_dir() -> Path:
    """Return store directory, overridable via AIND_SESSION_CACHE_DIR env var."""
    return Path(os.environ.get("AIND_SESSION_CACHE_DIR", str(_DEFAULT_STORE_DIR)))


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _frozenset_to_str(s: frozenset[str] | None) -> str:
    if not s:
        return ""
    return ",".join(sorted(s))


def _str_to_frozenset(s: str) -> frozenset[str]:
    if not s:
        return frozenset()
    return frozenset(x.strip() for x in s.split(",") if x.strip())


def session_result_to_row(sr: "SessionResult") -> dict:
    """Flatten a SessionResult to a dict suitable for a parquet row."""
    me = sr.manifest_entry or {}
    ep = sr.expected_pipelines
    return {
        "session_name": sr.session_name,
        "subject_id": sr.subject_id,
        "session_datetime": (
            sr.acquisition_datetime.isoformat()
            if sr.acquisition_datetime else ""
        ),
        "raw_modalities": _frozenset_to_str(sr.raw_modalities),
        "display_name": sr.display_name,
        "manifest_status": me.get("status", ""),
        "manifest_rig": me.get("rig", ""),
        "manifest_session_raw": me.get("session_raw", ""),
        "dts_status": sr.dts_status or "",
        "dts_job_url": sr.dts_job_url,
        "within_14d": sr.within_14d,
        "raw_asset_name": sr.raw_asset_name or "",
        "raw_docdb_id": sr.raw_docdb_id or "",
        "raw_co_asset_id": sr.raw_co_asset_id or "",
        "expected_pipelines": _frozenset_to_str(ep) if ep is not None else "__unknown__",
        "_settled": False,  # caller sets this after completeness check
        "_last_updated": datetime.now(tz=timezone.utc).isoformat(),
    }


def derived_asset_to_rows(sr: "SessionResult") -> list[dict]:
    """Flatten derived assets of a SessionResult to a list of dicts."""
    rows = []
    for da in sr.derived_assets:
        rows.append({
            "session_name": sr.session_name,
            "asset_name": da.asset_name,
            "docdb_id": da.docdb_id or "",
            "modalities": _frozenset_to_str(da.modalities),
            "co_asset_id": da.co_asset_id or "",
            "co_log_url": da.co_log_url or "",
        })
    return rows


# ---------------------------------------------------------------------------
# Store class
# ---------------------------------------------------------------------------

class ParquetSessionStore:
    """Local parquet implementation of the session cache."""

    def __init__(self, store_dir: Optional[Path] = None):
        self._dir = Path(store_dir) if store_dir else get_store_dir()
        self._sessions_path = self._dir / "sessions.parquet"
        self._derived_path = self._dir / "derived_assets.parquet"

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def load_sessions(self, session_names: set[str] | None = None) -> pd.DataFrame:
        """Load session rows. Pass session_names to filter; None = all."""
        if not self._sessions_path.exists():
            return pd.DataFrame()
        try:
            df = pd.read_parquet(self._sessions_path)
            if session_names is not None:
                df = df[df["session_name"].isin(session_names)]
            return df
        except Exception as exc:
            logger.warning("store: load_sessions failed: %s", exc)
            return pd.DataFrame()

    def load_derived_assets(self, session_names: set[str] | None = None) -> pd.DataFrame:
        """Load derived asset rows for given sessions."""
        if not self._derived_path.exists():
            return pd.DataFrame()
        try:
            df = pd.read_parquet(self._derived_path)
            if session_names is not None:
                df = df[df["session_name"].isin(session_names)]
            return df
        except Exception as exc:
            logger.warning("store: load_derived_assets failed: %s", exc)
            return pd.DataFrame()

    def get_settled_names(self, session_names: set[str]) -> set[str]:
        """Return subset of session_names that are marked settled."""
        df = self.load_sessions(session_names)
        if df.empty or "_settled" not in df.columns:
            return set()
        return set(df.loc[df["_settled"] == True, "session_name"])

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def _upsert(self, path: Path, new_df: pd.DataFrame, pk: str) -> None:
        """Upsert new_df into parquet file at path, keyed by pk column."""
        if new_df.empty:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            if path.exists():
                existing = pd.read_parquet(path)
                mask = ~existing[pk].isin(new_df[pk])
                combined = pd.concat([existing[mask], new_df], ignore_index=True)
            else:
                combined = new_df
            combined.to_parquet(path, index=False)
        except Exception as exc:
            logger.warning("store: upsert to %s failed: %s", path.name, exc)

    def save_sessions(self, rows: list[dict]) -> None:
        """Upsert session rows (list of dicts from session_result_to_row)."""
        if not rows:
            return
        self._upsert(self._sessions_path, pd.DataFrame(rows), "session_name")

    def save_derived_assets(self, rows: list[dict]) -> None:
        """Upsert derived asset rows (list of dicts from derived_asset_to_rows)."""
        if not rows:
            return
        # Upsert by session_name: drop all existing rows for these sessions.
        session_names = {r["session_name"] for r in rows}
        new_df = pd.DataFrame(rows)
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            if self._derived_path.exists():
                existing = pd.read_parquet(self._derived_path)
                mask = ~existing["session_name"].isin(session_names)
                combined = pd.concat([existing[mask], new_df], ignore_index=True)
            else:
                combined = new_df
            combined.to_parquet(self._derived_path, index=False)
        except Exception as exc:
            logger.warning("store: save_derived_assets failed: %s", exc)

    def mark_settled(self, session_names: set[str]) -> None:
        """Mark the given sessions as settled in the parquet file."""
        if not self._sessions_path.exists():
            return
        try:
            df = pd.read_parquet(self._sessions_path)
            df.loc[df["session_name"].isin(session_names), "_settled"] = True
            df.to_parquet(self._sessions_path, index=False)
        except Exception as exc:
            logger.warning("store: mark_settled failed: %s", exc)

    def refresh(self, session_names: set[str]) -> None:
        """Force sessions back to unsettled so they are re-queried next load.

        # TODO: expose this via a "force refresh" button or ?refresh=1 URL parameter
        # in the viewer so users can re-query sessions whose metadata has changed.
        """
        if not self._sessions_path.exists():
            return
        try:
            df = pd.read_parquet(self._sessions_path)
            df.loc[df["session_name"].isin(session_names), "_settled"] = False
            df.to_parquet(self._sessions_path, index=False)
        except Exception as exc:
            logger.warning("store: refresh failed: %s", exc)

    def clear(self) -> None:
        """Delete all stored parquet files."""
        for p in [self._sessions_path, self._derived_path]:
            try:
                p.unlink(missing_ok=True)
                logger.info("store: deleted %s", p)
            except Exception as exc:
                logger.warning("store: clear %s failed: %s", p.name, exc)


# ---------------------------------------------------------------------------
# Reconstruct SessionResult from stored row + supplementary live data
# ---------------------------------------------------------------------------

def session_result_from_row(
    row: dict,
    derived_rows: list[dict],
    watchdog_events_dict: dict[str, list[dict]],
) -> "SessionResult":
    """Reconstruct a SessionResult from a stored parquet row.

    Args:
        row:                  Dict from sessions.parquet (one session).
        derived_rows:         Rows from derived_assets.parquet for this session.
        watchdog_events_dict: Live watchdog events keyed by session_name.
    """
    from aind_session_utils.session import DerivedAssetInfo, SessionResult
    from aind_session_utils.sources.rig_logs import find_rig_log

    sname = row["session_name"]

    # Reconstruct manifest_entry if rig was set.
    manifest_rig = row.get("manifest_rig", "")
    manifest_status = row.get("manifest_status", "")
    manifest_session_raw = row.get("manifest_session_raw", "")
    manifest_entry = (
        {
            "status": manifest_status,
            "rig": manifest_rig,
            "session_raw": manifest_session_raw,
        }
        if manifest_rig
        else None
    )

    # Rig log path — re-derived from stored rig name.
    rig_log_path = find_rig_log(manifest_rig, sname) if manifest_rig else None

    # expected_pipelines — "__unknown__" sentinel means None.
    ep_str = row.get("expected_pipelines", "__unknown__")
    if ep_str == "__unknown__":
        expected_pipelines = None
    else:
        expected_pipelines = _str_to_frozenset(ep_str) or frozenset()

    # Acquisition datetime.
    dt_str = row.get("session_datetime", "")
    try:
        acq_dt = datetime.fromisoformat(dt_str) if dt_str else None
    except ValueError:
        acq_dt = None

    # Derived assets.
    derived_assets = tuple(
        DerivedAssetInfo(
            asset_name=dr["asset_name"],
            docdb_id=dr.get("docdb_id") or None,
            modalities=_str_to_frozenset(dr.get("modalities", "")),
            co_asset_id=dr.get("co_asset_id") or None,
            co_log_url=dr.get("co_log_url") or None,
        )
        for dr in derived_rows
    )

    return SessionResult(
        session_name=sname,
        subject_id=row.get("subject_id", ""),
        acquisition_datetime=acq_dt,
        raw_modalities=_str_to_frozenset(row.get("raw_modalities", "")),
        display_name=row.get("display_name", sname),
        rig_log_path=rig_log_path,
        manifest_entry=manifest_entry,
        watchdog_events=tuple(watchdog_events_dict.get(sname, [])),
        dts_status=row.get("dts_status") or None,
        dts_job_url=row.get("dts_job_url", ""),
        within_14d=bool(row.get("within_14d", True)),
        raw_asset_name=row.get("raw_asset_name") or None,
        raw_docdb_id=row.get("raw_docdb_id") or None,
        raw_co_asset_id=row.get("raw_co_asset_id") or None,
        expected_pipelines=expected_pipelines,
        derived_assets=derived_assets,
    )
