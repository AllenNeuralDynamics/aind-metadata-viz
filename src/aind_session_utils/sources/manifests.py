"""Rig-side manifest file parsing."""

import logging
import os
import re

from aind_session_utils.naming import get_session_name

logger = logging.getLogger(__name__)

AIND_LOGS_DIR = (
    "/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs"
)
MANIFEST_DIR = os.path.join(AIND_LOGS_DIR, "watchdog_manifests")

# Matches a file-entry line in a Windows `dir` listing, e.g.:
#   03/18/2026  09:35 AM     764 manifest_behavior_841859_2026-03-18_09-35-42.yml
_MANIFEST_LINE_RE = re.compile(
    r"^\s*\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2} [AP]M\s+[\d,]+\s+(manifest_\S+\.yml)\s*$"
)


def is_available() -> bool:
    """Return True if the rig manifest directory is accessible."""
    return os.path.isdir(MANIFEST_DIR)


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
