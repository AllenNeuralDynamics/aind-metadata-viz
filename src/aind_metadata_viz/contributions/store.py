"""SQLite-backed storage for ProjectContributions.

Each project's versions are stored as rows in a SQLite database
(default: ``~/.aind_contributions/contributions.db``).

* ``store_contributions`` inserts a new version row and returns its UUID.
* ``get_contributions`` returns the latest version or a specific one by UUID.
* ``list_project_commits`` returns the version history newest-first.
* ``set_project_password`` protects a project with a PBKDF2-hashed password.
* ``verify_project_password`` checks a supplied password against the stored hash.
* ``get_contributions_by_doi`` finds the latest version of any project by DOI.

Built-in examples are re-seeded on every fresh process startup so that
deploying updated code always serves current built-in data.
"""

import base64
import hashlib
import hmac
import os
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_passwords (
                project_id TEXT PRIMARY KEY,
                salt       TEXT NOT NULL,
                pw_hash    TEXT NOT NULL
            )
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


_PBKDF2_ITERATIONS = 200_000


def set_project_password(
    project_name: str,
    password: str,
    store_dir: Optional[Path] = None,
) -> None:
    """Protect a project with a password.

    ``password`` should be a pre-hashed string supplied by the client (e.g.
    a SHA-256 hex digest of the raw password).  It is stretched with
    PBKDF2-HMAC-SHA-256 before being written to the database so the stored
    value cannot be used directly to authenticate.
    """
    store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
    _ensure_db(store_dir)

    salt = os.urandom(32)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)

    with _connect(store_dir) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO project_passwords (project_id, salt, pw_hash) VALUES (?, ?, ?)",
            (
                project_name,
                base64.b64encode(salt).decode(),
                base64.b64encode(pw_hash).decode(),
            ),
        )


def verify_project_password(
    project_name: str,
    password: str,
    store_dir: Optional[Path] = None,
) -> bool:
    """Return True if *password* matches the stored hash for *project_name*.

    Returns True unconditionally when no password has been set for the
    project (i.e. the project is publicly accessible).
    """
    store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
    _ensure_db(store_dir)

    with _connect(store_dir) as conn:
        row = conn.execute(
            "SELECT salt, pw_hash FROM project_passwords WHERE project_id = ?",
            (project_name,),
        ).fetchone()

    if row is None:
        return True

    salt = base64.b64decode(row[0])
    stored_hash = base64.b64decode(row[1])
    check_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(check_hash, stored_hash)


def get_contributions_by_doi(
    doi: str,
    store_dir: Optional[Path] = None,
) -> ProjectContributions:
    """Return the latest version of any project whose DOI matches *doi*.

    Raises ``FileNotFoundError`` when no matching project is found.
    """
    store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
    _ensure_db(store_dir)

    with _connect(store_dir) as conn:
        rows = conn.execute(
            """
            SELECT v.project_id, v.data
            FROM versions v
            INNER JOIN (
                SELECT project_id, MAX(timestamp) AS max_ts
                FROM versions
                GROUP BY project_id
            ) latest ON v.project_id = latest.project_id
                     AND v.timestamp = latest.max_ts
            """
        ).fetchall()

    for project_id, data in rows:
        contrib = _from_json(data)
        if contrib.doi == doi:
            return contrib

    raise FileNotFoundError(f"No project found with DOI '{doi}'")
