"""Export a CSV summary of every project in the contributions database.

Reads the latest version of each project under
``s3://aind-scratch-data/contributions-app/`` and writes one row per project
to a CSV file with simple metadata.

Usage::

    python scripts/export_projects_csv.py [output.csv]

Default output path is ``contributions_projects.csv`` in the current directory.
"""

import csv
import json
import sys
from pathlib import Path

import boto3

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from aind_metadata_viz.contributions.store import (  # noqa: E402
    _S3_BUCKET,
    _S3_PREFIX,
    _get_json,
)


def _list_latest_project_keys() -> dict[str, str]:
    """Return a mapping of ``safe_project_id -> latest S3 key`` for every project."""
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    latest: dict[str, str] = {}
    for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=f"{_S3_PREFIX}/"):
        for obj in page.get("Contents", []):
            key: str = obj["Key"]
            parts = key[len(f"{_S3_PREFIX}/"):].split("/")
            if len(parts) < 2 or parts[0].startswith("_") or parts[0] == "images":
                continue
            project_id = parts[0]
            if key > latest.get(project_id, ""):
                latest[project_id] = key
    return latest


def _summarize(version_obj: dict) -> dict:
    project_name = version_obj.get("project_id", "")
    raw = version_obj.get("data", "{}")
    data = json.loads(raw) if isinstance(raw, str) else raw

    contributors = data.get("contributors", []) or []
    sections = data.get("sections", []) or []
    assets = data.get("assets", []) or []
    doi = data.get("doi") or ""

    return {
        "project_name": project_name or data.get("project_name", ""),
        "num_authors": len(contributors),
        "locked": bool(data.get("edit_locked", False)),
        "doi": doi,
        "num_assets": len(assets),
        "num_sections": len(sections),
        "last_updated": version_obj.get("timestamp", ""),
    }


def main(output_path: Path) -> None:
    print(f"Listing projects in s3://{_S3_BUCKET}/{_S3_PREFIX}/ ...")
    latest = _list_latest_project_keys()
    print(f"  Found {len(latest)} project(s).")

    rows: list[dict] = []
    for safe_id, key in sorted(latest.items()):
        obj = _get_json(key)
        if not obj:
            print(f"  Skipping {safe_id}: could not load {key}")
            continue
        rows.append(_summarize(obj))

    rows.sort(key=lambda r: r["project_name"].lower())

    fieldnames = [
        "project_name",
        "num_authors",
        "locked",
        "doi",
        "num_assets",
        "num_sections",
        "last_updated",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} row(s) to {output_path}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("contributions_projects.csv")
    main(out)
