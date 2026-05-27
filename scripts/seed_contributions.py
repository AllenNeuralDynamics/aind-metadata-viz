"""One-time script to seed built-in example ProjectContributions into S3.

Run this once after deploying to populate
  s3://aind-scratch-data/contributions-app/

Existing versions for a project are left untouched, so it is safe to re-run.

Usage::

    python scripts/seed_contributions.py
"""

import sys
from pathlib import Path

# Allow running from the repo root without an editable install
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from datetime import datetime, timezone

from examples.authorship_extractor import (
    AUTHORSHIP_PROJECT_NAME,
    authorship_extractor_contributions,
)
from examples.authorship_extractor_real import (
    AUTHORSHIP_REAL_PROJECT_NAME,
    authorship_extractor_real_contributions,
)
from examples.np_opto import (
    NP_OPTO_PROJECT_NAME,
    np_opto_contributions,
)
from aind_metadata_viz.contributions.serializers import to_json
from aind_metadata_viz.contributions.store import (
    _list_version_keys,
    _put_json,
    _safe_key,
    _version_prefix,
)

EXAMPLES = [
    (AUTHORSHIP_PROJECT_NAME, authorship_extractor_contributions),
    (AUTHORSHIP_REAL_PROJECT_NAME, authorship_extractor_real_contributions),
    (NP_OPTO_PROJECT_NAME, np_opto_contributions),
]


def seed():
    ts = datetime.now(timezone.utc).isoformat()
    for project_name, factory in EXAMPLES:
        if _list_version_keys(project_name):
            print(f"  skip  {project_name!r} — versions already exist")
            continue
        seed_id = f"seed_{_safe_key(project_name)}"
        key = f"{_version_prefix(project_name)}{ts}_{seed_id}.json"
        _put_json(key, {
            "id": seed_id,
            "project_id": project_name,
            "timestamp": ts,
            "message": f"Built-in seed for {project_name}",
            "data": to_json(factory()),
        })
        print(f"  seeded {project_name!r}")


if __name__ == "__main__":
    print("Seeding built-in contribution examples to S3...")
    seed()
    print("Done.")
