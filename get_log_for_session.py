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

# Shared with the server — same file and format so running this script also
# warms the server's cache (and the server's background warmup helps this script).
CACHE_FILE  = Path.home() / ".cache" / "aind_metadata_viz" / "co_pipeline_run_cache.json"


def load_cache() -> dict:
    """Load the shared run cache from disk, or return an empty cache."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_cache(cache: dict) -> None:
    """Persist the shared run cache to disk."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache))


def update_cache(cache: dict, pipeline_id: str, co: CodeOcean, t0: float) -> dict:
    """
    Fetch new runs for pipeline_id and merge them into the shared cache.

    The cache is keyed by pipeline_id (same format as the server), so updating
    one pipeline never clobbers another's watermark.

    Returns the updated cache.
    """
    all_runs = co.capsules.list_computations(pipeline_id)
    newest = datetime.fromtimestamp(all_runs[0].created) if all_runs else None
    oldest = datetime.fromtimestamp(all_runs[-1].created) if all_runs else None
    print(f"  [{time.time()-t0:.1f}s] fetched {len(all_runs)} total runs "
          f"({oldest.date() if oldest else '?'} to {newest.date() if newest else '?'})")

    pipeline_cache = cache.setdefault(pipeline_id, {"asset_to_run": {}, "newest_created": 0})
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

    pipeline_cache["last_updated"] = time.time()
    print(f"  [{time.time()-t0:.1f}s] added {new_count} new run(s) to cache "
          f"({len(asset_to_run)} total asset mappings)")
    save_cache(cache)
    return cache


def find_log_by_asset_id(
    asset_name: str,
    pipeline_id: str,
    co: CodeOcean,
) -> str | None:
    """
    Find a pipeline log by matching the input data asset UUID.

    Checks the shared cache (~/.cache/aind_metadata_viz/) first — instant if
    the server has already warmed it.  On a miss, fetches new runs, updates
    the cache, and tries again.

    Args:
        asset_name: Name of the raw CO data asset.
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
    pipeline_cache = cache.get(pipeline_id, {})

    # Fast path: asset already in cache.
    run_id = pipeline_cache.get("asset_to_run", {}).get(asset.id)
    if run_id:
        print(f"  [{time.time()-t0:.1f}s] cache hit — run {run_id}, fetching log...")
    else:
        # Slow path: fetch new runs, update cache, try again.
        print(f"  [{time.time()-t0:.1f}s] not in cache — fetching new runs from pipeline...")
        cache = update_cache(cache, pipeline_id, co, t0)
        run_id = cache.get(pipeline_id, {}).get("asset_to_run", {}).get(asset.id)
        if not run_id:
            print(f"  [{time.time()-t0:.1f}s] no run found with asset '{asset_name}' as input")
            return None

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
