"""
Find and print the pipeline log for a given session by matching the input data asset UUID.

Maintains a local cache of {input_asset_id -> run_id} built from the pipeline's computation
history. Cache lookups are instant. The slow list_computations API call is only made when
the asset is not in the cache (i.e. a new failure since the last cache update), and only
new runs are added on each update.

Usage:
    uv run python get_log_for_session.py --session-name behavior_825002_2026-03-11_13-35-19
"""
import argparse
import json
import os
import requests
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from codeocean import CodeOcean
from codeocean.data_asset import DataAssetSearchParams
import time

CO_DOMAIN   = "https://codeocean.allenneuraldynamics.org"
PIPELINE_ID = "250cf9b5-f438-4d31-9bbb-ba29dab47d56"  # Dynamic Foraging pipeline
CACHE_FILE  = Path(".co_pipeline_cache.json")


def load_cache() -> dict:
    """Load the local run cache from disk, or return an empty cache."""
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {"asset_to_run": {}, "newest_created": 0, "oldest_created": None}


def save_cache(cache: dict) -> None:
    """Persist the run cache to disk."""
    CACHE_FILE.write_text(json.dumps(cache))


def update_cache(cache: dict, pipeline_id: str, co: CodeOcean, t0: float) -> dict:
    """
    Fetch new runs from the pipeline and add them to the cache.

    Iterates the full run list (newest-first) and stops as soon as we reach
    a run already in the cache, so only truly new runs are processed.

    Returns the updated cache.
    """
    all_runs = co.capsules.list_computations(pipeline_id)
    newest = datetime.fromtimestamp(all_runs[0].created) if all_runs else None
    oldest = datetime.fromtimestamp(all_runs[-1].created) if all_runs else None
    print(f"  [{time.time()-t0:.1f}s] fetched {len(all_runs)} total runs ({oldest.date() if oldest else '?'} to {newest.date() if newest else '?'})")

    newest_cached = cache.get("newest_created", 0)
    new_count = 0
    for run in all_runs:
        if run.created <= newest_cached:
            break  # everything from here is already cached
        for da in (run.data_assets or []):
            cache["asset_to_run"][da.id] = run.id
        cache["newest_created"] = max(cache["newest_created"], run.created)
        if cache["oldest_created"] is None or run.created < cache["oldest_created"]:
            cache["oldest_created"] = run.created
        new_count += 1

    print(f"  [{time.time()-t0:.1f}s] added {new_count} new run(s) to cache ({len(cache['asset_to_run'])} total asset mappings)")
    save_cache(cache)
    return cache


def find_log_by_asset_id(
    asset_name: str,
    pipeline_id: str,
    co: CodeOcean,
) -> str | None:
    """
    Find a pipeline log by matching the input data asset UUID.

    Checks the local cache first. If the asset is not cached (new failure since last
    update), fetches fresh run data, updates the cache, then searches again.
    Once the matching run is identified, fetches and returns its log text.

    Args:
        asset_name: Name of the raw CO data asset (e.g. behavior_825002_2026-03-11_13-35-19).
        pipeline_id: Code Ocean pipeline UUID.
        co: Authenticated CodeOcean client.

    Returns:
        Full log text of the matching run, or None if not found.
    """
    t0 = time.time()

    # Look up the raw asset's CO UUID by name.
    results = co.data_assets.search_data_assets(
        DataAssetSearchParams(query=f'name:"{asset_name}"', limit=5)
    )
    asset = next((a for a in results.results if a.name == asset_name), None)
    if asset is None:
        print(f"  [{time.time()-t0:.1f}s] asset '{asset_name}' not found in Code Ocean")
        return None
    print(f"  [{time.time()-t0:.1f}s] found raw asset UUID: {asset.id}")

    cache = load_cache()

    # Fast path: asset already in cache.
    run_id = cache["asset_to_run"].get(asset.id)
    if run_id:
        print(f"  [{time.time()-t0:.1f}s] cache hit — run {run_id}, fetching log...")
    else:
        # Slow path: fetch new runs, update cache, try again.
        print(f"  [{time.time()-t0:.1f}s] not in cache — fetching new runs from pipeline...")
        cache = update_cache(cache, pipeline_id, co, t0)
        run_id = cache["asset_to_run"].get(asset.id)
        if not run_id:
            print(f"  [{time.time()-t0:.1f}s] no run found with asset '{asset_name}' as input")
            return None
        run_created = None  # we don't store created per-run in the cache

    urls = co.computations.get_result_file_urls(run_id, "output")
    r = requests.get(urls.view_url, timeout=30)
    print(f"  [{time.time()-t0:.1f}s] log fetched")
    return r.text if r.ok else None


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Print pipeline log for a session.")
    parser.add_argument("--session-name", required=True, help="e.g. behavior_825002_2026-03-11_13-35-19")
    parser.add_argument("--clear-cache", action="store_true", help="Delete the local cache and rebuild from scratch")
    args = parser.parse_args()

    if args.clear_cache and CACHE_FILE.exists():
        CACHE_FILE.unlink()
        print("Cache cleared.")

    token = os.environ.get("CODEOCEAN_API_TOKEN")
    if not token:
        raise SystemExit("Set CODEOCEAN_API_TOKEN in your .env file")

    co = CodeOcean(domain=CO_DOMAIN, token=token)
    print(f"Searching for log: {args.session_name}")
    log = find_log_by_asset_id(args.session_name, PIPELINE_ID, co)
    print("\n--- LOG OUTPUT ---" if log else "No log found for this session.")
    if log:
        print(log)


if __name__ == "__main__":
    main()
