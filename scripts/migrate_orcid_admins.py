#!/usr/bin/env python3
"""One-time migration: link existing projects to their admin ORCID iDs.

Background
----------
Contributions auth moved from per-project passwords to ORCID login. This script
retroactively records, for each *real* project, who its administrator is by
writing a *project-admin* member record (``is_admin: true`` in
``contributions-app/_members/{project}.json``). A project admin has the same
power the old password granted: full edit access to every author row plus
management of the invite link.

Mapping (explicit allowlist — anything not listed here is left untouched, so
test projects never get an admin)::

    np-opto          read-only  -> locked (no admins); only global admins edit
    data-schema      admin      -> 0000-0003-3748-6289 (Daniel Birman; also global admin)
    p3_data_release  admin      -> 0000-0002-0131-0938 (Jerome Lecoq)
    giant-pipeline   admin      -> 0000-0002-4026-9181 (Michael E. Xie)

For each admin that is also an author on the project, their author row's
``registry_identifier`` is stamped with the correct ORCID (creating it when
missing, and overwriting a value that isn't a valid ORCID — e.g. a name that was
mistakenly stored there).

The script is **idempotent** and prints a plan by default. Nothing is written to
S3 unless ``--apply`` is passed. Requires AWS credentials for the prod account
with read/write access to the ``aind-scratch-data`` bucket.

Usage::

    python scripts/migrate_orcid_admins.py               # dry run (default)
    python scripts/migrate_orcid_admins.py --apply       # perform the migration
    python scripts/migrate_orcid_admins.py --apply --unlock-admined  # also unlock admined projects
"""

import argparse
import re
import secrets
import sys
import unicodedata
from pathlib import Path

# Allow running from a source checkout without installing the package.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aind_metadata_viz.contributions.store import (  # noqa: E402
    add_member,
    clear_project_password,
    get_contributions,
    is_project_admin,
    is_project_locked,
    list_all_projects,
    list_members,
    set_project_password,
    store_contributions,
)

# --- configuration -----------------------------------------------------------

# Projects to lock (read-only): no admins; only global ADMIN_ORCIDS can edit.
READONLY_LOCK = {"np-opto"}

# project name -> (admin ORCID, admin display name or None)
PROJECT_ADMINS = {
    "data-schema": ("0000-0003-3748-6289", "Daniel Birman"),
    "p3_data_release": ("0000-0002-0131-0938", "Jerome Lecoq"),
    "giant-pipeline": ("0000-0002-4026-9181", "Michael E. Xie"),
}

MANAGED = READONLY_LOCK | set(PROJECT_ADMINS)

_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def _valid_orcid(s) -> bool:
    return bool(s) and bool(_ORCID_RE.match(str(s)))


def _norm(s: str) -> str:
    """Casefold and strip accents for tolerant name matching."""
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().strip()


def _find_author(contribs, orcid, name):
    """Return the contributor row belonging to (orcid, name), or None."""
    for c in contribs.contributors:
        if orcid and getattr(c.author, "registry_identifier", None) == orcid:
            return c
    target = _norm(name)
    if target:
        for c in contribs.contributors:
            if _norm(c.author.name) == target:
                return c
        surname = target.split()[-1]
        matches = [c for c in contribs.contributors if surname in _norm(c.author.name)]
        if len(matches) == 1:
            return matches[0]
    return None


def _ensure_project_admin(project, orcid, name, apply):
    if is_project_admin(project, orcid):
        return f"already project admin ({orcid})"
    if apply:
        add_member(project, orcid, name=name, granted_via="migration", is_admin=True)
        return f"ADDED project admin {orcid}"
    return f"WOULD ADD project admin {orcid}"


def _ensure_author_orcid(project, orcid, name, apply):
    if not name:
        return "no admin name to match; ORCID not stamped"
    try:
        contribs = get_contributions(project)
    except FileNotFoundError:
        return "no contribution data; ORCID not stamped"
    author = _find_author(contribs, orcid, name)
    if author is None:
        return f"note: '{name}' is not an author on this project; nothing to stamp"
    current = getattr(author.author, "registry_identifier", None)
    if current == orcid:
        return f"author '{author.author.name}' already has ORCID {orcid}"
    if _valid_orcid(current) and current != orcid:
        return (
            f"WARNING: author '{author.author.name}' has a different valid ORCID "
            f"({current}); left unchanged"
        )
    # current is empty or not a valid ORCID (e.g. a name) -> set/overwrite.
    verb = "overwrite invalid" if current else "set missing"
    if apply:
        author.author.registry_identifier = orcid
        store_contributions(
            project, contribs, message=f"migration: link {name} ORCID {orcid}"
        )
        return f"STAMPED ORCID {orcid} onto '{author.author.name}' ({verb} value {current!r})"
    return f"WOULD STAMP ORCID {orcid} onto '{author.author.name}' ({verb} value {current!r})"


def _lock_readonly(project, apply):
    if is_project_locked(project):
        return "already locked (read-only)"
    if apply:
        # Lock with an unguessable secret nobody uses; edits go through global
        # admins' ORCID session, and anonymous/non-admin POSTs are rejected.
        set_project_password(project, secrets.token_hex(32))
        return "LOCKED (read-only)"
    return "WOULD LOCK (read-only)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="perform the migration (default: dry run)")
    parser.add_argument("--unlock-admined", action="store_true",
                        help="also remove passwords from admined projects (enables "
                             "the anonymous 'continue without logging in' self-add path)")
    args = parser.parse_args()

    print(f"=== ORCID admin migration — {'APPLY' if args.apply else 'DRY RUN (no writes)'} ===\n")

    projects = list_all_projects()
    print(f"Found {len(projects)} project(s).\n")

    for project in projects:
        if project not in MANAGED:
            print(f"- {project}\n    not in migration mapping; left untouched\n")
            continue

        print(f"- {project}  (locked={is_project_locked(project)}, members={len(list_members(project))})")
        if project in READONLY_LOCK:
            print(f"    {_lock_readonly(project, args.apply)}")
            print()
            continue

        orcid, name = PROJECT_ADMINS[project]
        print(f"    {_ensure_project_admin(project, orcid, name, args.apply)}")
        print(f"    {_ensure_author_orcid(project, orcid, name, args.apply)}")
        if args.unlock_admined and is_project_locked(project):
            if args.apply:
                clear_project_password(project)
                print("    UNLOCKED (password removed)")
            else:
                print("    WOULD UNLOCK (password removed)")
        print()

    # Warn about any mapped project that wasn't found in the store.
    missing = sorted(MANAGED - set(projects))
    if missing:
        print(f"NOTE: mapped projects not found in the store: {missing}\n")

    print("Dry run complete — re-run with --apply." if not args.apply else "Migration complete.")


if __name__ == "__main__":
    main()
