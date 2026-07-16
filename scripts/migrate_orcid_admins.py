#!/usr/bin/env python3
"""One-time migration: link existing projects to their admin ORCID iDs.

Background
----------
Contributions auth moved from per-project passwords to ORCID login. This script
retroactively records, for each existing project, who its administrator is by
writing a *project-admin* member record (``is_admin: true`` in
``contributions-app/_members/{project}.json``). A project admin has the same
power the old password granted: full edit access to every author row plus
management of the invite link.

Mapping (per the migration request)
-----------------------------------
* ``np-opto``      — stays read-only: no admins added; left as-is.
* ``data-schema``  — project admin ``0000-0003-3748-6289`` (also the sole global
                     admin, configured separately via ``ADMIN_ORCIDS``).
* every other project — project admin **Jerome Lecoq**
                     (``0000-0002-0131-0938``); his author row in the project
                     data is also stamped with that ORCID if it is missing.

The script is **idempotent** and prints a plan by default. Nothing is written to
S3 unless ``--apply`` is passed. Requires AWS credentials with read/write access
to the ``aind-scratch-data`` bucket.

Usage::

    python scripts/migrate_orcid_admins.py               # dry run (default)
    python scripts/migrate_orcid_admins.py --apply       # perform the migration
    python scripts/migrate_orcid_admins.py --apply --unlock   # also remove passwords
"""

import argparse
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
    store_contributions,
)

# --- configuration -----------------------------------------------------------

GLOBAL_ADMIN_ORCID = "0000-0003-3748-6289"
JEROME_ORCID = "0000-0002-0131-0938"
JEROME_NAME = "Jerome Lecoq"

READONLY_PROJECTS = {"np-opto"}
PROJECT_ADMINS = {
    # project name -> (orcid, display name)
    "data-schema": (GLOBAL_ADMIN_ORCID, None),
}
# Any project not listed above and not read-only is administered by Jerome.
DEFAULT_ADMIN = (JEROME_ORCID, JEROME_NAME)


def _norm(s: str) -> str:
    """Casefold and strip accents for tolerant name matching."""
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().strip()


def _find_author(contribs, orcid, name):
    """Return the contributor whose row belongs to (orcid, name), or None.

    Matches by ORCID (``registry_identifier``) first, then by a tolerant name
    comparison, then by surname containment as a last resort.
    """
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
    """Make (orcid) a project admin of (project). Returns a status string."""
    if is_project_admin(project, orcid):
        return f"already project admin ({orcid})"
    if apply:
        add_member(project, orcid, name=name, granted_via="migration", is_admin=True)
        return f"ADDED project admin {orcid}"
    return f"WOULD ADD project admin {orcid}"


def _ensure_author_orcid(project, orcid, name, apply):
    """Stamp (orcid) onto the author's row in the project data if missing."""
    try:
        contribs = get_contributions(project)
    except FileNotFoundError:
        return "no contribution data found; skipped ORCID stamp"
    author = _find_author(contribs, orcid, name)
    if author is None:
        return f"WARNING: author '{name}' not found in data; ORCID not stamped"
    current = getattr(author.author, "registry_identifier", None)
    if current == orcid:
        return f"author '{author.author.name}' already has ORCID {orcid}"
    if current:
        return (
            f"WARNING: author '{author.author.name}' has a different ORCID "
            f"({current}); left unchanged"
        )
    if apply:
        author.author.registry_identifier = orcid
        store_contributions(
            project, contribs, message=f"migration: link {name} ORCID {orcid}"
        )
        return f"STAMPED ORCID {orcid} onto author '{author.author.name}'"
    return f"WOULD STAMP ORCID {orcid} onto author '{author.author.name}'"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the migration (default is a dry run that only prints a plan)",
    )
    parser.add_argument(
        "--unlock",
        action="store_true",
        help=(
            "also remove the password from non-read-only projects, making them "
            "publicly writable (required for the anonymous 'continue without "
            "logging in' self-add path; ORCID members/admins work either way)"
        ),
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN (no writes)"
    print(f"=== ORCID admin migration — {mode} ===\n")

    projects = list_all_projects()
    print(f"Found {len(projects)} project(s): {', '.join(projects) or '(none)'}\n")

    unexpected = [
        p
        for p in projects
        if p not in READONLY_PROJECTS and p not in PROJECT_ADMINS
    ]
    if len(unexpected) != 1:
        print(
            "NOTE: expected exactly one 'other' project to tie to Jerome Lecoq, "
            f"but found {len(unexpected)}: {unexpected}. Each will be tied to "
            "Jerome. Review before applying.\n"
        )

    for project in projects:
        print(f"- {project}")
        locked = is_project_locked(project)
        print(f"    lock: {'password-protected' if locked else 'open'}")

        if project in READONLY_PROJECTS:
            existing = list_members(project)
            print(f"    read-only: leaving as-is ({len(existing)} member record(s), "
                  "no admins added)")
            print()
            continue

        orcid, name = PROJECT_ADMINS.get(project, DEFAULT_ADMIN)
        print(f"    {_ensure_project_admin(project, orcid, name, args.apply)}")

        # Stamp the ORCID onto the admin's own author row (Jerome / the default
        # admin); for data-schema the global admin has no author row to stamp.
        if (orcid, name) == DEFAULT_ADMIN:
            print(f"    {_ensure_author_orcid(project, orcid, name, args.apply)}")

        if args.unlock and locked:
            if args.apply:
                removed = clear_project_password(project)
                print(f"    {'UNLOCKED (password removed)' if removed else 'no password to remove'}")
            else:
                print("    WOULD UNLOCK (remove password)")
        print()

    if not args.apply:
        print("Dry run complete. Re-run with --apply to perform the migration.")
    else:
        print("Migration complete.")


if __name__ == "__main__":
    main()
