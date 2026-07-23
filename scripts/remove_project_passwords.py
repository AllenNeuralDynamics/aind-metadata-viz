"""Delete all legacy project-password and token objects from S3.

The contributions app no longer uses project passwords or scoped tokens — auth
is entirely by ORCID session plus the admin ``edit_locked`` flag. This one-time
migration removes the now-dead objects under::

    s3://aind-scratch-data/contributions-app/_passwords/
    s3://aind-scratch-data/contributions-app/_tokens/

Run with AWS credentials that have delete access to that bucket/prefix.

Usage::

    python scripts/remove_project_passwords.py --dry-run   # list only
    python scripts/remove_project_passwords.py             # actually delete

Deletion is irreversible; always review the ``--dry-run`` output first.
"""

import argparse
import sys
from pathlib import Path

import boto3

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from aind_metadata_viz.contributions.store import (  # noqa: E402
    _S3_BUCKET,
    _S3_PREFIX,
)

_PREFIXES = [
    f"{_S3_PREFIX}/_passwords/",
    f"{_S3_PREFIX}/_tokens/",
]


def _list_keys(s3, prefix: str) -> list:
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the objects that would be deleted without deleting them",
    )
    args = parser.parse_args()

    s3 = boto3.client("s3")

    total = 0
    for prefix in _PREFIXES:
        keys = _list_keys(s3, prefix)
        print(f"\n{prefix} — {len(keys)} object(s)")
        for key in keys:
            if args.dry_run:
                print(f"  would delete: {key}")
            else:
                s3.delete_object(Bucket=_S3_BUCKET, Key=key)
                print(f"  deleted: {key}")
        total += len(keys)

    verb = "would be deleted" if args.dry_run else "deleted"
    print(f"\n{total} object(s) {verb}.")


if __name__ == "__main__":
    main()
