"""Data Transfer Service queries."""

import logging

import requests as req

logger = logging.getLogger(__name__)

DTS_BASE_URL = "http://aind-data-transfer-service"
DTS_MAX_LOOKBACK_DAYS = 14


def get_dts_jobs(date_from_iso: str, date_to_iso: str) -> tuple[list[dict], str | None]:
    """
    Fetch DTS jobs server-side, paginating as needed.

    Returns (jobs_list, error_message_or_None).
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
