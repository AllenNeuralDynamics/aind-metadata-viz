"""Git-backed storage for ProjectContributions.

Each project is stored as a CSV file named ``<project_name>.csv`` inside a
dedicated git repository (default: ``~/.aind_contributions/``).

* ``store_contributions`` writes/updates the CSV and creates a commit.
* ``get_contributions`` reads HEAD or a specific commit hash.

CSV layout
----------
One row per author.  Columns:

    name, affiliation, email, registry, registry_identifier, <role1>, <role2>, ...

where each role column contains the contribution level ("lead", "supporting",
"equal") or an empty string when the author has no credit for that role.
"""

import csv
import io
import subprocess
from pathlib import Path
from typing import Optional, Union

from .models import (
    Author,
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)
from .serializers import load as _load

from aind_data_schema_models.registries import Registry


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_STORE_DIR = Path.home() / ".aind_contributions"

# Ordered column names for the CSV
_FIXED_COLS = ["name", "affiliation", "email", "registry", "registry_identifier"]
_ROLE_COLS = [role.value for role in CreditRole]
_ALL_COLS = _FIXED_COLS + _ROLE_COLS


# ---------------------------------------------------------------------------
# Internal git helpers
# ---------------------------------------------------------------------------


def _run(args: list, cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git command {args} failed:\n{result.stderr.strip()}"
        )
    return result


def _ensure_repo(store_dir: Path) -> bool:
    """Initialise a bare git repo at *store_dir* if one does not exist.

    Returns True if the repo was newly created.
    """
    store_dir.mkdir(parents=True, exist_ok=True)
    git_dir = store_dir / ".git"
    if not git_dir.exists():
        _run(["git", "init"], store_dir)
        _run(["git", "config", "user.name", "aind-contributions"], store_dir)
        _run(["git", "config", "user.email", "aind-contributions@local"], store_dir)
        return True
    return False


# ---------------------------------------------------------------------------
# CSV serialisation helpers
# ---------------------------------------------------------------------------


def _contributions_to_csv(contributions: ProjectContributions) -> str:
    """Serialise *contributions* to a CSV string."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_ALL_COLS, lineterminator="\n")
    writer.writeheader()
    for ac in contributions.contributors:
        row: dict = {col: "" for col in _ALL_COLS}
        row["name"] = ac.author.name
        row["affiliation"] = ac.author.affiliation
        row["email"] = ac.author.email or ""
        row["registry"] = (
            ac.author.registry.value
            if hasattr(ac.author.registry, "value")
            else str(ac.author.registry)
        )
        row["registry_identifier"] = ac.author.registry_identifier or ""
        for rc in ac.credit_levels:
            row[rc.role.value] = rc.level.value
        writer.writerow(row)
    return buf.getvalue()


def _csv_to_contributions(project_name: str, csv_text: str) -> ProjectContributions:
    """Deserialise a CSV string back into a :class:`ProjectContributions`."""
    reader = csv.DictReader(io.StringIO(csv_text))
    contributors = []
    for row in reader:
        author_kwargs = {
            "name": row["name"],
            "affiliation": row.get("affiliation", ""),
            "email": row.get("email") or None,
            "registry_identifier": row.get("registry_identifier") or None,
        }
        try:
            author_kwargs["registry"] = Registry(row.get("registry", Registry.ORCID.value))
        except ValueError:
            author_kwargs["registry"] = Registry.ORCID
        author = Author(**author_kwargs)

        credit_levels = []
        for role in CreditRole:
            level_str = row.get(role.value, "")
            if level_str:
                try:
                    credit_levels.append(
                        RoleContribution(role=role, level=ContributionLevel(level_str))
                    )
                except ValueError:
                    continue

        contributors.append(AuthorContribution(author=author, credit_levels=credit_levels))

    return ProjectContributions(project_name=project_name, contributors=contributors)


# ---------------------------------------------------------------------------
# Default seeding
# ---------------------------------------------------------------------------


def _seed_defaults(store_dir: Path) -> None:
    """Seed the store with the IBL default example if not already present."""
    from .defaults import IBL_PROJECT_NAME, ibl_default_contributions

    filename = _safe_filename(IBL_PROJECT_NAME)
    if not (store_dir / filename).exists():
        store_contributions(IBL_PROJECT_NAME, ibl_default_contributions(), store_dir=store_dir)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _safe_filename(project_name: str) -> str:
    """Convert a project name to a safe filename (no path separators)."""
    return project_name.replace("/", "_").replace("\\", "_") + ".csv"


def store_contributions(
    project_name: str,
    data: Union[str, dict, ProjectContributions],
    message: Optional[str] = None,
    store_dir: Optional[Path] = None,
) -> str:
    """Write contribution data and create a git commit.

    Parameters
    ----------
    project_name:
        Unique name for this project.  Used as the filename stem.
    data:
        A :class:`ProjectContributions` instance, a JSON string, a YAML
        string (authors-real.yml style), or a plain dict.
    message:
        Optional commit message.  Defaults to
        ``"Update contributions for <project_name>"``.
    store_dir:
        Path to the git repository used for storage.
        Defaults to ``~/.aind_contributions/``.

    Returns
    -------
    str
        The full SHA-1 commit hash of the new commit.
    """
    store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
    is_new = _ensure_repo(store_dir)
    if is_new:
        _seed_defaults(store_dir)

    if isinstance(data, ProjectContributions):
        contributions = data
    else:
        contributions = _load(data)

    csv_text = _contributions_to_csv(contributions)
    filename = _safe_filename(project_name)
    file_path = store_dir / filename
    file_path.write_text(csv_text, encoding="utf-8")

    _run(["git", "add", filename], store_dir)

    # Check whether there is actually anything staged; if the file is identical
    # to the last commit we still make a commit (caller explicitly requested).
    commit_message = message or f"Update contributions for {project_name}"
    _run(["git", "commit", "--allow-empty", "-m", commit_message], store_dir)

    result = _run(["git", "rev-parse", "HEAD"], store_dir)
    return result.stdout.strip()


def get_contributions(
    project_name: str,
    commit_hash: Optional[str] = None,
    store_dir: Optional[Path] = None,
) -> ProjectContributions:
    """Retrieve contribution data, optionally at a specific commit.

    Parameters
    ----------
    project_name:
        The project name used when calling :func:`store_contributions`.
    commit_hash:
        A full or abbreviated git commit SHA.  If ``None`` the latest
        committed version (HEAD) is returned.
    store_dir:
        Path to the git repository.  Defaults to ``~/.aind_contributions/``.

    Returns
    -------
    ProjectContributions
    """
    store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
    is_new = _ensure_repo(store_dir)
    if is_new:
        _seed_defaults(store_dir)

    filename = _safe_filename(project_name)
    ref = commit_hash or "HEAD"

    result = _run(["git", "show", f"{ref}:{filename}"], store_dir)
    csv_text = result.stdout
    return _csv_to_contributions(project_name, csv_text)
