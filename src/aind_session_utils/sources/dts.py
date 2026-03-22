"""Data Transfer Service (DTS) job queries.

Talks to the AIND Data Transfer Service REST API at ``DTS_BASE_URL``
(``http://aind-data-transfer-service``).  Requires AIND network or VPN.

The DTS enforces a 14-day lookback window (``DTS_MAX_LOOKBACK_DAYS``); queries
for older date ranges return an empty list without error.

Primary entry point: ``get_dts_jobs(date_from_iso, date_to_iso)`` — paginates
through all matching job records and returns ``(jobs_list, error_or_None)``.
Results are cached in memory for ``_DTS_CACHE_TTL`` seconds so repeated loads
of the same date range don't re-hit the API.
"""

import logging
import time as _time

import requests as req

logger = logging.getLogger(__name__)

DTS_BASE_URL = "http://aind-data-transfer-service"
DTS_MAX_LOOKBACK_DAYS = 14
_DTS_CACHE_TTL = 300  # seconds; DTS jobs change frequently during the day

_dts_cache: dict[tuple[str, str], tuple[float, list[dict], str | None]] = {}


def is_available() -> bool:
    """Return True if the DTS API is reachable."""
    try:
        req.head(f"{DTS_BASE_URL}/api/v1/get_job_status_list", timeout=3)
        return True
    except Exception:
        return False


def get_dts_jobs(date_from_iso: str, date_to_iso: str) -> tuple[list[dict], str | None]:
    """Fetch DTS jobs server-side, paginating as needed.

    Results are cached for ``_DTS_CACHE_TTL`` seconds (default 5 min) to
    avoid redundant requests when the user clicks Load Sessions repeatedly.

    Returns:
        ``(jobs_list, error_message_or_None)``
    """
    cache_key = (date_from_iso, date_to_iso)
    cached = _dts_cache.get(cache_key)
    if cached is not None:
        ts, jobs, err = cached
        if _time.time() - ts < _DTS_CACHE_TTL:
            return jobs, err

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
        _dts_cache[cache_key] = (_time.time(), all_jobs, None)
        return all_jobs, None
    except Exception as e:
        err = str(e)
        _dts_cache[cache_key] = (_time.time(), [], err)
        return [], err
