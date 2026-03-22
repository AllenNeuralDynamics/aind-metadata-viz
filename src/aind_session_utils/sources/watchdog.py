"""Watchdog log events from eng-logtools."""

import logging
import re as _re
import time as _time
from datetime import timedelta

import requests as req

from aind_session_utils.naming import get_session_name

logger = logging.getLogger(__name__)

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
