"""Git-backed storage for ProjectContributions.

Each project is stored as a JSON file named ``<project_name>.json`` inside a
dedicated git repository (default: ``~/.aind_contributions/``).

* ``store_contributions`` writes/updates the JSON and creates a commit.
* ``get_contributions`` reads HEAD or a specific commit hash.
"""

import subprocess
from pathlib import Path
from typing import Optional, Union

from .models import (
    ProjectContributions,
)
from .serializers import load as _load, to_json as _to_json


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_STORE_DIR = Path.home() / ".aind_contributions"


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
# JSON serialisation helpers
# ---------------------------------------------------------------------------


def _contributions_to_json(contributions: ProjectContributions) -> str:
    """Serialise *contributions* to a JSON string."""
    return _to_json(contributions)


def _json_to_contributions(project_name: str, json_text: str) -> ProjectContributions:
    """Deserialise a JSON string back into a :class:`ProjectContributions`."""
    from .serializers import from_json as _from_json
    return _from_json(json_text)


# ---------------------------------------------------------------------------
# Default seeding
# ---------------------------------------------------------------------------


def _seed_defaults(store_dir: Path) -> None:
    """Seed the store with the IBL default example if not already present."""
    from .examples.defaults import IBL_PROJECT_NAME, ibl_default_contributions

    filename = _safe_filename(IBL_PROJECT_NAME)
    if not (store_dir / filename).exists():
        store_contributions(IBL_PROJECT_NAME, ibl_default_contributions(), store_dir=store_dir)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _safe_filename(project_name: str) -> str:
    """Convert a project name to a safe filename (no path separators)."""
    return project_name.replace("/", "_").replace("\\", "_") + ".json"


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

    json_text = _contributions_to_json(contributions)
    filename = _safe_filename(project_name)
    file_path = store_dir / filename
    file_path.write_text(json_text, encoding="utf-8")

    _run(["git", "add", filename], store_dir)

    commit_message = message or f"Update contributions for {project_name}"
    _run(["git", "commit", "--allow-empty", "-m", commit_message], store_dir)

    result = _run(["git", "rev-parse", "HEAD"], store_dir)
    return result.stdout.strip()


def list_project_commits(
    project_name: str,
    store_dir: Optional[Path] = None,
) -> list:
    """Return the commit history for a single project file, newest first.

    Parameters
    ----------
    project_name:
        The project name used when calling :func:`store_contributions`.
    store_dir:
        Path to the git repository.  Defaults to ``~/.aind_contributions/``.

    Returns
    -------
    list of dict
        Each entry has keys ``commit``, ``timestamp`` (ISO-8601), and
        ``message``.  The list is ordered newest-first.
    """
    store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
    _ensure_repo(store_dir)

    filename = _safe_filename(project_name)
    result = _run(
        ["git", "log", "--format=%H|||%aI|||%s", "--", filename],
        store_dir,
    )
    commits = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|||", 2)
        if len(parts) != 3:
            continue
        commits.append({"commit": parts[0], "timestamp": parts[1], "message": parts[2]})

    if not commits:
        raise FileNotFoundError(f"No commits found for project '{project_name}'")

    return commits


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
    return _json_to_contributions(project_name, result.stdout)
