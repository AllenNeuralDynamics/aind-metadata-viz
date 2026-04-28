"""SQLite-backed storage for ProjectContributions.

Each project's versions are stored as rows in a SQLite database
(default: ``~/.aind_contributions/contributions.db``).

* ``store_contributions`` inserts a new version row and returns its UUID.
* ``get_contributions`` returns the latest version or a specific one by UUID.
* ``list_project_commits`` returns the version history newest-first.

Built-in examples are re-seeded on every fresh process startup so that
deploying updated code always serves current built-in data.
"""

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from .models import ProjectContributions
from .serializers import from_json as _from_json, load as _load, to_json as _to_json

DEFAULT_STORE_DIR = Path.home() / ".aind_contributions"
_DB_FILENAME = "contributions.db"

_initialized: set = set()


@contextmanager
def _connect(store_dir: Path):
    conn = sqlite3.connect(str(store_dir / _DB_FILENAME))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_db(store_dir: Path) -> None:
    if store_dir in _initialized:
        return
    store_dir.mkdir(parents=True, exist_ok=True)
    with _connect(store_dir) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS versions (
                id         TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                timestamp  TEXT NOT NULL,
                message    TEXT NOT NULL,
                data       TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_versions_project_ts
                ON versions (project_id, timestamp DESC)
            """
        )
    _seed_defaults(store_dir)
    _initialized.add(store_dir)


def _seed_defaults(store_dir: Path) -> None:
    from .examples.authorship_extractor import AUTHORSHIP_PROJECT_NAME, authorship_extractor_contributions
    from .examples.authorship_extractor_real import AUTHORSHIP_REAL_PROJECT_NAME, authorship_extractor_real_contributions
    from .examples.defaults import IBL_PROJECT_NAME, ibl_default_contributions
    from .examples.ibl_decision import IBL_DECISION_PROJECT_NAME, ibl_decision_contributions

    examples = [
        (IBL_PROJECT_NAME, ibl_default_contributions),
        (AUTHORSHIP_PROJECT_NAME, authorship_extractor_contributions),
        (AUTHORSHIP_REAL_PROJECT_NAME, authorship_extractor_real_contributions),
        (IBL_DECISION_PROJECT_NAME, ibl_decision_contributions),
    ]
    ts = datetime.now(timezone.utc).isoformat()
    with _connect(store_dir) as conn:
        for project_name, factory in examples:
            seed_id = f"seed:{project_name}"
            conn.execute(
                "INSERT OR REPLACE INTO versions (id, project_id, timestamp, message, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (seed_id, project_name, ts, f"Built-in seed for {project_name}", _to_json(factory())),
            )


def _safe_filename(project_name: str) -> str:
    return project_name.replace("/", "_").replace("\\", "_") + ".json"


def store_contributions(
    project_name: str,
    data: Union[str, dict, ProjectContributions],
    message: Optional[str] = None,
    store_dir: Optional[Path] = None,
) -> str:
    store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
    _ensure_db(store_dir)

    if isinstance(data, ProjectContributions):
        contributions = data
    else:
        contributions = _load(data)

    version_id = uuid.uuid4().hex
    ts = datetime.now(timezone.utc).isoformat()
    commit_message = message or f"Update contributions for {project_name}"
    with _connect(store_dir) as conn:
        conn.execute(
            "INSERT INTO versions (id, project_id, timestamp, message, data) VALUES (?, ?, ?, ?, ?)",
            (version_id, project_name, ts, commit_message, _to_json(contributions)),
        )
    return version_id


def list_project_commits(
    project_name: str,
    store_dir: Optional[Path] = None,
) -> list:
    store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
    _ensure_db(store_dir)

    with _connect(store_dir) as conn:
        rows = conn.execute(
            "SELECT id, timestamp, message FROM versions "
            "WHERE project_id = ? ORDER BY timestamp DESC",
            (project_name,),
        ).fetchall()

    if not rows:
        raise FileNotFoundError(f"No commits found for project '{project_name}'")

    return [{"commit": r[0], "timestamp": r[1], "message": r[2]} for r in rows]


def get_contributions(
    project_name: str,
    commit_hash: Optional[str] = None,
    store_dir: Optional[Path] = None,
) -> ProjectContributions:
    store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
    _ensure_db(store_dir)

    with _connect(store_dir) as conn:
        if commit_hash is not None:
            row = conn.execute(
                "SELECT data FROM versions WHERE id = ? AND project_id = ?",
                (commit_hash, project_name),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(
                    f"Project '{project_name}' not found at ref '{commit_hash}'"
                )
        else:
            row = conn.execute(
                "SELECT data FROM versions WHERE project_id = ? ORDER BY timestamp DESC LIMIT 1",
                (project_name,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"Project '{project_name}' not found")

    return _from_json(row[0])
