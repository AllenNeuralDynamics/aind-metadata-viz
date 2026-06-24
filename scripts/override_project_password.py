"""Override (set or reset) the password for a contributions project.

The contributions backend hashes whatever string the client supplies with
PBKDF2-HMAC-SHA-256 (+ a fresh random 32-byte salt) before storing it in S3.
The web UI sends a SHA-256 hex digest of the user's raw password, so this
script does the same so that resulting credentials are interchangeable with
ones set via the website.

Run with AWS credentials that have write access to
``s3://aind-scratch-data/contributions-app/_passwords/``.

Usage::

    python scripts/override_project_password.py "<project name>"

You will be prompted (no echo) to enter and confirm the new raw password.
This **overwrites** any existing password for the project.
"""

import argparse
import getpass
import hashlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from aind_metadata_viz.contributions.store import (  # noqa: E402
    is_project_locked,
    set_project_password,
)


def _sha256_hex(raw_password: str) -> str:
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


def _prompt_password() -> str:
    pw1 = getpass.getpass("New password: ")
    if not pw1:
        sys.exit("Aborted: empty password.")
    pw2 = getpass.getpass("Confirm new password: ")
    if pw1 != pw2:
        sys.exit("Aborted: passwords do not match.")
    return pw1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", help="Exact project name to override the password for")
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the interactive confirmation prompt",
    )
    args = parser.parse_args()

    project = args.project
    already_locked = is_project_locked(project)
    state = "is currently locked" if already_locked else "is currently unlocked"
    print(f"Project: {project!r} ({state})")

    if not args.yes:
        confirm = input(
            "This will overwrite any existing password. Type the project name to confirm: "
        ).strip()
        if confirm != project:
            sys.exit("Aborted: confirmation did not match project name.")

    raw_password = _prompt_password()
    set_project_password(project, _sha256_hex(raw_password))
    print(f"Password set for project {project!r}.")


if __name__ == "__main__":
    main()
