"""Code Ocean asset and computation queries."""

import json
import logging
import os
import time as _time
from pathlib import Path

import requests as req
from codeocean import CodeOcean
from codeocean.data_asset import DataAssetSearchParams, DataAssetState
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CO_DOMAIN: str = os.environ.get("CODEOCEAN_DOMAIN", "")
_co_client: CodeOcean | None = None
_co_url_cache: dict[str, str | None] = {}
_co_derived_id_cache: dict[str, str | None] = {}
_co_raw_id_cache: dict[str, str | None] = {}

# Cache mapping input asset UUID -> computation run ID, built from list_computations.
# Persisted to disk so it survives server restarts.
_CO_RUN_CACHE_FILE = Path.home() / ".cache" / "aind_session_utils" / "co_pipeline_run_cache.json"

# Keyed by pipeline_id so each pipeline maintains its own asset→run mapping and
# newest_created watermark. Structure:
#   { pipeline_id: { "asset_to_run": {asset_uuid: run_id},
#                    "newest_created": int, "last_updated": float } }
_co_run_cache: dict[str, dict] = {}


def _get_co_client() -> CodeOcean | None:
    """Return a singleton CodeOcean client if credentials are configured."""
    global _co_client
    if _co_client is None:
        token = os.environ.get("CODEOCEAN_API_TOKEN")
        if CO_DOMAIN and token:
            _co_client = CodeOcean(domain=CO_DOMAIN, token=token)
    return _co_client


def _load_co_run_cache() -> None:
    """Load the per-pipeline run cache from disk into module-level state."""
    global _co_run_cache
    if _CO_RUN_CACHE_FILE.exists():
        try:
            _co_run_cache = json.loads(_CO_RUN_CACHE_FILE.read_text())
            total = sum(len(v.get("asset_to_run", {})) for v in _co_run_cache.values())
            logger.info("Loaded CO run cache: %d entries across %d pipeline(s)", total, len(_co_run_cache))
        except Exception as e:
            logger.warning("Failed to load CO run cache: %s", e)


def _save_co_run_cache() -> None:
    """Persist the per-pipeline run cache to disk."""
    try:
        _CO_RUN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CO_RUN_CACHE_FILE.write_text(json.dumps(_co_run_cache))
    except Exception as e:
        logger.warning("Failed to save CO run cache: %s", e)


def _update_co_run_cache(pipeline_id: str) -> None:
    """
    Fetch new runs for a specific pipeline and add them to that pipeline's cache.

    Each pipeline has its own asset→run mapping and newest_created watermark,
    so updating one pipeline never affects the watermark of another.

    This call is unconditional — callers are responsible for deciding whether an
    update is needed (e.g. by checking whether any pending sessions have unknown
    UUIDs that are newer than ``last_updated``).
    """
    co = _get_co_client()
    if co is None:
        return
    try:
        all_runs = co.capsules.list_computations(pipeline_id)
    except Exception as e:
        logger.warning("list_computations failed for %s: %s", pipeline_id, e)
        return

    pipeline_cache = _co_run_cache.setdefault(pipeline_id, {"asset_to_run": {}, "newest_created": 0})
    newest_cached = pipeline_cache["newest_created"]
    asset_to_run = pipeline_cache["asset_to_run"]

    new_count = 0
    for run in all_runs:
        if run.created <= newest_cached:
            break  # everything from here is already cached
        for da in (run.data_assets or []):
            asset_to_run[da.id] = run.id
        if run.created > pipeline_cache["newest_created"]:
            pipeline_cache["newest_created"] = run.created
        new_count += 1

    pipeline_cache["last_updated"] = _time.time()
    logger.info("CO run cache updated for pipeline %s: %d new runs, %d total entries",
                pipeline_id, new_count, len(asset_to_run))
    _save_co_run_cache()


def _get_run_id_for_asset(asset_uuid: str, pipeline_id: str) -> str | None:
    """
    Return the computation run ID for a given raw asset UUID and pipeline.

    Cache hit (asset already known): instant dict lookup.
    Cache miss: fetches any new runs added since the last update (newest_created
    watermark), then checks again.  The slow list_computations call is only made
    on a genuine miss — once the cache is built it is never expired.
    """
    pipeline_cache = _co_run_cache.get(pipeline_id, {})
    run_id = pipeline_cache.get("asset_to_run", {}).get(asset_uuid)
    if run_id:
        return run_id
    # Cache miss: pull any new runs since last update, then re-check.
    _update_co_run_cache(pipeline_id)
    return _co_run_cache.get(pipeline_id, {}).get("asset_to_run", {}).get(asset_uuid)


def get_cached_run_id(asset_uuid: str, pipeline_id: str) -> str | None:
    """Cache-only lookup of a computation run ID — no API call.

    Returns the run ID if the asset is already in the local run cache,
    or None if not found.  Never triggers a list_computations fetch.
    Use this for display purposes; use get_pipeline_log for on-demand fetches.
    """
    return (
        _co_run_cache.get(pipeline_id, {})
        .get("asset_to_run", {})
        .get(asset_uuid)
    )


def get_co_output_url(asset_name: str) -> str | None:
    """
    Return the Code Ocean output log URL for a derived asset name.

    Returns:
        A URL string  — if the CO data asset is Ready
        'pending'     — if the asset exists but is not yet complete
        None          — if not found or CO is unavailable

    Results are cached in memory for the server lifetime (CO asset states
    are effectively immutable once Ready).
    """
    if asset_name in _co_url_cache:
        return _co_url_cache[asset_name]
    co = _get_co_client()
    if co is None:
        return None
    try:
        results = co.data_assets.search_data_assets(
            DataAssetSearchParams(query=asset_name, limit=5)
        )
        asset = next(
            (a for a in results.results if a.name == asset_name), None
        )
        if asset is None:
            result: str | None = None
            _co_derived_id_cache[asset_name] = None
        elif asset.state != DataAssetState.Ready:
            result = "pending"
            _co_derived_id_cache[asset_name] = asset.id
        else:
            result = f"{CO_DOMAIN}/data-assets/{asset.id}/{asset.name}/output"
            _co_derived_id_cache[asset_name] = asset.id
    except Exception as e:
        logger.warning("CO log lookup failed for %s: %s", asset_name, e)
        result = None
    _co_url_cache[asset_name] = result
    return result


def get_raw_co_asset_id(raw_asset_name: str) -> str | None:
    """Look up the Code Ocean UUID for a raw asset by exact name. Cached."""
    if raw_asset_name in _co_raw_id_cache:
        return _co_raw_id_cache[raw_asset_name]
    co = _get_co_client()
    if co is None:
        return None
    try:
        results = co.data_assets.search_data_assets(
            DataAssetSearchParams(query=raw_asset_name, limit=5)
        )
        asset = next(
            (a for a in results.results if a.name == raw_asset_name), None
        )
        result: str | None = asset.id if asset else None
    except Exception as e:
        logger.warning("CO raw asset lookup failed for %s: %s", raw_asset_name, e)
        result = None
    _co_raw_id_cache[raw_asset_name] = result
    return result


def get_pipeline_log(
    raw_asset_name: str,
    capsule_id: str,
) -> tuple[str | None, str]:
    """Fetch the pipeline log for a session given its raw asset name and capsule.

    Encapsulates the full lookup chain:
      1. Resolve raw asset name → CO UUID (from _co_raw_id_cache, pre-populated
         at table-load time by build_sessions).
      2. Resolve UUID → computation run ID (from _co_run_cache, warmed by the
         background thread at table-load time — instant for found runs).
      3. Fetch the log text via the computation result file URL.

    Args:
        raw_asset_name: DocDB/CO name of the raw data asset.
        capsule_id:     Code Ocean pipeline capsule UUID.

    Returns:
        ``(log_text, "")`` on success, or ``(None, error_message)`` on failure.
    """
    co = _get_co_client()
    if co is None:
        return None, "Code Ocean client not configured."

    raw_uuid = _co_raw_id_cache.get(raw_asset_name)
    if not raw_uuid:
        return None, "Raw asset not found in Code Ocean."

    run_id = _get_run_id_for_asset(raw_uuid, capsule_id)
    if not run_id:
        return None, (
            "No pipeline run found for this session. "
            "The pipeline may not have been triggered."
        )

    try:
        urls = co.computations.get_result_file_urls(run_id, "output")
        r = req.get(urls.view_url, timeout=30)
        r.raise_for_status()
        return r.text, ""
    except Exception as exc:
        logger.warning("Failed to fetch pipeline log for %s: %s", raw_asset_name, exc)
        return None, f"Failed to load pipeline log: {exc}"


# Load disk cache on module import
_load_co_run_cache()
