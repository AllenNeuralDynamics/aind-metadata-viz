"""Tornado request handlers for the contributions REST endpoints.

Routes
------
GET  /contributions/get?project=<name>[&commit=<hash>]
    Returns the latest (or specified) contribution data as JSON.
    All models are publicly readable without a password.

GET  /contributions/get?doi=<doi-or-project-name>
    Looks up by DOI first; falls back to treating the value as a project name.

GET  /contributions/get?project=<name>&history=true
    Returns a list of commits for the project, newest first.
    Each entry: {"commit": "<sha>", "timestamp": "<iso8601>", "message": "<str>"}

POST /contributions/post?project=<name>[&password=<hash>]
    Body: JSON or YAML string of contribution data.
    Stores a new versioned commit and returns the commit hash.
    If *password* is supplied and the project has no password yet, the project
    is locked with that password going forward.
    If the project is already locked, *password* must match the stored hash;
    omitting or supplying the wrong value returns 401.
"""

import json

from tornado.web import RequestHandler

from . import from_json, from_yaml, get_contributions, list_project_commits, store_contributions, to_json, to_yaml
from .models import ProjectContributions
from .store import (
    consume_token,
    create_token,
    get_contributions_by_doi,
    is_project_locked,
    lookup_token,
    set_project_password,
    verify_project_password,
)


def _validate_token_scope(project_name, token_type, author_name, new_contributions):
    """Return ``(ok, error_message)`` for token-scoped change validation.

    Compares *new_contributions* against the currently stored version to
    enforce the restrictions of *token_type*:

    * ``"add_author"`` — all existing authors must remain unchanged; exactly
      one new author may be added.
    * ``"edit_author"`` — only the author identified by *author_name* may
      be modified; no authors may be added or removed.
    """
    try:
        existing = get_contributions(project_name)
    except FileNotFoundError:
        existing = None

    existing_names = {c.author.name for c in existing.contributors} if existing else set()
    new_names = {c.author.name for c in new_contributions.contributors}

    if token_type == "add_author":
        removed = existing_names - new_names
        if removed:
            return False, (
                "add_author token cannot remove existing authors: "
                + ", ".join(sorted(removed))
            )
        added = new_names - existing_names
        if len(added) != 1:
            return False, "add_author token allows adding exactly one new author"
        if existing:
            existing_by_name = {c.author.name: c for c in existing.contributors}
            for c in new_contributions.contributors:
                if c.author.name in existing_by_name:
                    if c.model_dump_json() != existing_by_name[c.author.name].model_dump_json():
                        return False, (
                            f"add_author token cannot modify existing author '{c.author.name}'"
                        )
        return True, None

    if token_type == "edit_author":
        if author_name not in existing_names:
            return False, f"Author '{author_name}' not found in project"
        if new_names != existing_names:
            return False, "edit_author token cannot add or remove authors"
        if existing:
            existing_by_name = {c.author.name: c for c in existing.contributors}
            for c in new_contributions.contributors:
                if c.author.name == author_name:
                    continue
                old = existing_by_name.get(c.author.name)
                if old and c.model_dump_json() != old.model_dump_json():
                    return False, (
                        f"edit_author token can only modify author '{author_name}'"
                    )
        return True, None

    return False, "Unknown token type"


def _resolve_project(identifier):
    """Return ``(contributions, project_name)`` for a DOI or project name.

    Tries DOI lookup first; if no project has that DOI, falls back to treating
    *identifier* as a project name.
    Raises ``FileNotFoundError`` when neither lookup finds anything.
    """
    try:
        contributions = get_contributions_by_doi(identifier)
        return contributions, contributions.project_name
    except FileNotFoundError:
        pass
    contributions = get_contributions(identifier)
    return contributions, identifier


class ContributionsGetHandler(RequestHandler):
    """Return contribution data for a project (HEAD or a specific commit)."""

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")

    def options(self):
        self.set_status(204)

    def get(self):
        self.set_header("Content-Type", "application/json")
        project = self.get_argument("project", None)
        doi = self.get_argument("doi", None)

        if not project and not doi:
            self.set_status(400)
            self.write(json.dumps({"error": "project or doi query parameter is required"}))
            return

        if doi:
            try:
                contributions, project_name = _resolve_project(doi)
            except FileNotFoundError as e:
                self.set_status(404)
                self.write(json.dumps({"error": str(e)}))
                return
            except Exception as e:
                self.set_status(500)
                self.write(json.dumps({"error": str(e)}))
                return

            password = self.get_argument("password", None)
            if not verify_project_password(project_name, password or ""):
                self.set_status(401)
                self.write(json.dumps({"error": "Unauthorized"}))
                return

            contributions.locked = is_project_locked(project_name)
            fmt = self.get_argument("format", "json").lower()
            self.set_status(200)
            if fmt == "yaml":
                self.set_header("Content-Type", "text/plain; charset=utf-8")
                self.write(to_yaml(contributions))
            else:
                self.set_header("Content-Type", "application/json")
                self.write(to_json(contributions))
            return

        if self.get_argument("history", None) == "true":
            try:
                commits = list_project_commits(project)
            except FileNotFoundError as e:
                self.set_status(404)
                self.write(json.dumps({"error": str(e)}))
                return
            except Exception as e:
                self.set_status(500)
                self.write(json.dumps({"error": str(e)}))
                return
            self.set_status(200)
            self.write(json.dumps(commits))
            return

        commit = self.get_argument("commit", None)
        fmt = self.get_argument("format", "json").lower()

        try:
            contributions = get_contributions(project, commit_hash=commit)
        except FileNotFoundError as e:
            self.set_status(404)
            self.write(json.dumps({"error": str(e)}))
            return
        except Exception as e:
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))
            return

        contributions.locked = is_project_locked(project)
        self.set_status(200)
        if fmt == "yaml":
            self.set_header("Content-Type", "text/plain; charset=utf-8")
            self.write(to_yaml(contributions))
        else:
            self.set_header("Content-Type", "application/json")
            self.write(to_json(contributions))


class ContributionsPostHandler(RequestHandler):
    """Store a new version of contribution data for a project."""

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")

    def options(self):
        self.set_status(204)

    def post(self):
        self.set_header("Content-Type", "application/json")
        project = self.get_argument("project", None)
        if not project:
            self.set_status(400)
            self.write(json.dumps({"error": "project query parameter is required"}))
            return

        body = self.request.body
        if not body:
            self.set_status(400)
            self.write(json.dumps({"error": "request body is required"}))
            return

        try:
            data = body.decode("utf-8")
            stripped = data.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                new_contributions = from_json(stripped)
            else:
                new_contributions = from_yaml(stripped)
        except Exception as e:
            self.set_status(400)
            self.write(json.dumps({"error": f"Failed to parse body: {e}"}))
            return

        password = self.get_argument("password", None)
        token_id = None
        token_type = None

        if password:
            token_record = lookup_token(project, password)
            if token_record is not None:
                token_id = password
                token_type = token_record["token_type"]
                token_author = token_record.get("author_name")
                ok, err = _validate_token_scope(project, token_type, token_author, new_contributions)
                if not ok:
                    self.set_status(403)
                    self.write(json.dumps({"error": err}))
                    return
            else:
                if not verify_project_password(project, password):
                    self.set_status(401)
                    self.write(json.dumps({"error": "Unauthorized"}))
                    return
        else:
            if not verify_project_password(project, ""):
                self.set_status(401)
                self.write(json.dumps({"error": "Unauthorized"}))
                return

        if password and token_id is None and not is_project_locked(project):
            set_project_password(project, password)

        message = self.get_argument("message", None)

        try:
            commit_hash = store_contributions(project, new_contributions, message=message)
        except Exception as e:
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))
            return

        if token_id and token_type == "add_author":
            consume_token(project, token_id)

        self.set_status(200)
        self.write(json.dumps({"commit": commit_hash, "project": project}))


class ContributionsTokenHandler(RequestHandler):
    """Create a scoped one-time or reusable token for a project.

    GET /contributions/token
        ?doi=<doi-or-project-name>
        &type=add_author|edit_author
        [&author=<name>]          required for edit_author
        [&days=<n>]               default 365, capped at 365
        [&password=<hash>]        required when the project is password-protected

    *doi* may be either a real DOI or a project name; the server tries DOI
    lookup first and falls back to project-name lookup automatically.

    Returns ``{"token": "<uuid>", "type": "<type>", "expires_days": <n>}``.
    Requires the admin password when the project is locked.
    """

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")

    def options(self):
        self.set_status(204)

    def get(self):
        self.set_header("Content-Type", "application/json")
        doi = self.get_argument("doi", None)
        if not doi:
            self.set_status(400)
            self.write(json.dumps({"error": "doi query parameter is required"}))
            return

        token_type = self.get_argument("type", None)
        if token_type not in ("add_author", "edit_author"):
            self.set_status(400)
            self.write(json.dumps({"error": "type must be 'add_author' or 'edit_author'"}))
            return

        author = self.get_argument("author", None)
        if token_type == "edit_author" and not author:
            self.set_status(400)
            self.write(json.dumps({"error": "author parameter is required for edit_author tokens"}))
            return

        days_str = self.get_argument("days", "365")
        try:
            days = int(days_str)
        except ValueError:
            self.set_status(400)
            self.write(json.dumps({"error": "days must be an integer"}))
            return

        try:
            _, project_name = _resolve_project(doi)
        except FileNotFoundError as e:
            self.set_status(404)
            self.write(json.dumps({"error": str(e)}))
            return
        except Exception as e:
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))
            return

        password = self.get_argument("password", None)
        if not verify_project_password(project_name, password or ""):
            self.set_status(401)
            self.write(json.dumps({"error": "Unauthorized"}))
            return

        try:
            token_id = create_token(project_name, token_type, author_name=author, expires_days=days)
        except Exception as e:
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))
            return

        capped_days = min(days, 365)
        self.set_status(200)
        self.write(json.dumps({"token": token_id, "type": token_type, "expires_days": capped_days}))


CONTRIBUTION_ROUTES = [
    (r"/contributions/get", ContributionsGetHandler),
    (r"/contributions/post", ContributionsPostHandler),
    (r"/contributions/token", ContributionsTokenHandler),
]
