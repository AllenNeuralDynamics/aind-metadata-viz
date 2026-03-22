"""Rig-side session log lookup."""

import logging
import os

from aind_session_utils.sources.manifests import AIND_LOGS_DIR

logger = logging.getLogger(__name__)

_gui_dir_cache: dict[str, list[str]] = {}  # rig → sorted list of all .txt paths


def find_rig_log(rig: str, session_name: str) -> str | None:
    """
    Find the GUI acquisition log file for a session on a given rig, or None.

    GUI logs live at {AIND_LOGS_DIR}/{rig}_gui_log/ and are named:
        {RIG}-{BOX}_gui_log_{YYYY-MM-DD}_{HH-MM-SS}.txt

    The filename timestamp is the GUI *launch* time, which is always before
    the session timestamp.  We find all logs on the session date, parse their
    timestamps, and return the one with the latest start time that is still
    at or before the session timestamp (i.e. the GUI that was running when
    the session was saved).

    Directory listings are cached per rig in _gui_dir_cache so that repeated
    calls for different sessions on the same rig do not re-scan the network share.
    """
    import glob as _glob
    from datetime import datetime as _dt

    parts = session_name.split("_")
    if len(parts) < 3:
        return None
    date_str, time_str = parts[1], parts[2]

    if rig not in _gui_dir_cache:
        all_files = _glob.glob(os.path.join(AIND_LOGS_DIR, f"{rig}_gui_log", "*.txt"))
        _gui_dir_cache[rig] = sorted(all_files)

    matches = [p for p in _gui_dir_cache[rig] if date_str in os.path.basename(p)]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
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
    return min(candidates, key=lambda x: x[0])[1]
