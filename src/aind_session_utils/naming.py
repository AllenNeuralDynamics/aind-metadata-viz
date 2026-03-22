"""Session name parsing and canonicalization."""

from datetime import datetime, timezone

_DERIVED_MARKERS = ("_processed_", "_videoprocessed_", "_sorted_")


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
