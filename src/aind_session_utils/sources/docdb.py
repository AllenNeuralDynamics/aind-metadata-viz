"""DocDB V1/V2 queries."""

import logging
from functools import lru_cache

from aind_data_access_api.document_db import MetadataDbClient

from aind_session_utils.naming import get_session_name, session_date

logger = logging.getLogger(__name__)

docdb_client_v1 = MetadataDbClient(host="api.allenneuraldynamics.org", version="v1")
docdb_client_v2 = MetadataDbClient(host="api.allenneuraldynamics.org", version="v2")

_DOCDB_CLIENTS = {"v1": docdb_client_v1, "v2": docdb_client_v2}

_DOCDB_BATCH_SIZE = 50  # max names per $in query to stay under URL size limits


def _chunked(seq, size):
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


@lru_cache(maxsize=8)
def get_project_records(
    project_names: tuple[str, ...],
    versions: tuple[str, ...],
) -> list[dict]:
    """
    Fetch all DocDB records (raw + derived) for the given projects, across the
    specified DB versions.  Results are merged by asset name; V2 takes precedence
    over V1 when the same asset exists in both.  Cached for 1 hour.

    Date filtering is intentionally omitted: older v1 records often store
    session/acquisition timestamps as datetime objects (not strings), so
    ISO-string $gte/$lte comparisons silently exclude them.  Client-side
    filtering (in build_sessions) uses the session name date as a reliable
    fallback and handles the date range precisely.
    """
    logger.info(
        "Querying DocDB for project records",
        extra={"projects": project_names, "versions": versions},
    )
    projection = {
        "name": 1,
        "_id": 1,
        "subject.subject_id": 1,
        "data_description.data_level": 1,
        "data_description.modalities": 1,
        "data_description.modality": 1,
        "acquisition.acquisition_start_time": 1,
        "session.session_start_time": 1,
    }

    # Collect V1 first, then V2 so V2 naturally overwrites on name collision.
    by_name: dict[str, dict] = {}
    for version in ("v1", "v2"):
        if version not in versions:
            continue
        client = _DOCDB_CLIENTS[version]
        for project_name in project_names:
            records = client.retrieve_docdb_records(
                filter_query={"data_description.project_name": project_name},
                projection=projection,
                limit=0,
                paginate_batch_size=500,
            )
            for r in records:
                by_name[r.get("name", "")] = r
    result = list(by_name.values())
    logger.info("DocDB query complete", extra={"count": len(result)})
    return result


def get_raw_records_by_names(
    names: tuple[str, ...],
    versions: tuple[str, ...],
) -> list[dict]:
    """
    Fast $in lookup for raw records by exact asset name.

    Used in Phase 1 of two-phase loading: DTS job names are the exact
    DocDB raw asset names, so this query uses the name index (<0.2s).
    Batched into chunks of _DOCDB_BATCH_SIZE to avoid 431 URL-too-large errors.
    Cached for 5 minutes to match DTS cache lifetime.
    """
    if not names:
        return []
    projection = {
        "name": 1,
        "_id": 1,
        "subject.subject_id": 1,
        "data_description.data_level": 1,
        "data_description.project_name": 1,
        "data_description.modalities": 1,
        "data_description.modality": 1,
        "acquisition.acquisition_start_time": 1,
        "session.session_start_time": 1,
    }
    by_name: dict[str, dict] = {}
    for version in ("v1", "v2"):
        if version not in versions:
            continue
        client = _DOCDB_CLIENTS[version]
        for chunk in _chunked(names, _DOCDB_BATCH_SIZE):
            records = client.retrieve_docdb_records(
                filter_query={"name": {"$in": chunk}},
                projection=projection,
                limit=0,
            )
            for r in records:
                by_name[r.get("name", "")] = r
    logger.info("Phase 1 raw $in query", extra={"count": len(by_name), "names_queried": len(names)})
    return list(by_name.values())


def get_derived_records_by_input_names(
    input_names: tuple[str, ...],
    versions: tuple[str, ...],
) -> list[dict]:
    """
    Fetch derived DocDB records by their input_data_name field.

    Derived assets store the name of their source raw asset in
    data_description.input_data_name.  Using $in on this field gives us
    exactly the derived records for the sessions found in Phase 1.
    This field is not indexed so the query is slow (~5-8s) — call from
    a background thread.  Batched to avoid 431 URL-too-large errors.
    Cached for 1 hour.
    """
    if not input_names:
        return []
    projection = {
        "name": 1,
        "_id": 1,
        "subject.subject_id": 1,
        "data_description.data_level": 1,
        "data_description.modalities": 1,
        "data_description.modality": 1,
        "acquisition.acquisition_start_time": 1,
        "session.session_start_time": 1,
    }
    by_name: dict[str, dict] = {}
    for version in ("v1", "v2"):
        if version not in versions:
            continue
        client = _DOCDB_CLIENTS[version]
        for chunk in _chunked(input_names, _DOCDB_BATCH_SIZE):
            records = client.retrieve_docdb_records(
                filter_query={"data_description.input_data_name": {"$in": chunk}},
                projection=projection,
                limit=0,
                paginate_batch_size=500,
            )
            for r in records:
                by_name[r.get("name", "")] = r
    logger.info("Phase 2 derived input_data_name $in query", extra={"count": len(by_name)})
    return list(by_name.values())


def get_full_record(name: str) -> dict | None:
    """
    Fetch the complete DocDB record for a single asset by name.

    Tries V2 first (newer schema), falls back to V1.  Returns None if not found.
    Cached for 1 hour — individual records rarely change.
    """
    for version in ("v2", "v1"):
        client = _DOCDB_CLIENTS[version]
        records = client.retrieve_docdb_records(
            filter_query={"name": name},
            limit=1,
        )
        if records:
            return records[0]
    return None


def filter_records_by_date(
    records: list[dict],
    date_from,
    date_to,
) -> list[dict]:
    """Filter records by the date encoded in the asset name."""
    result = []
    for r in records:
        d = session_date(get_session_name(r.get("name", "")))
        if d and date_from <= d <= date_to:
            result.append(r)
    return result
