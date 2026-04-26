"""Tornado request handlers for the contributions REST endpoints.

Routes
------
GET  /contributions/get?project=<name>[&commit=<hash>]
    Returns the latest (or specified) contribution data as JSON.

GET  /contributions/get?project=<name>&history=true
    Returns a list of commits for the project, newest first.
    Each entry: {"commit": "<sha>", "timestamp": "<iso8601>", "message": "<str>"}

POST /contributions/post?project=<name>
    Body: JSON or YAML string of contribution data.
    Stores a new versioned commit and returns the commit hash.
"""

import json

from tornado.web import RequestHandler

from . import from_json, from_yaml, get_contributions, list_project_commits, store_contributions, to_json, to_yaml
from .models import ProjectContributions


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
        if not project:
            self.set_status(400)
            self.write(json.dumps({"error": "project query parameter is required"}))
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
            # Accept JSON or YAML
            stripped = data.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                contributions = from_json(stripped)
            else:
                contributions = from_yaml(stripped)
        except Exception as e:
            self.set_status(400)
            self.write(json.dumps({"error": f"Failed to parse body: {e}"}))
            return

        message = self.get_argument("message", None)

        try:
            commit_hash = store_contributions(project, contributions, message=message)
        except Exception as e:
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))
            return

        self.set_status(200)
        self.write(json.dumps({"commit": commit_hash, "project": project}))


CONTRIBUTION_ROUTES = [
    (r"/contributions/get", ContributionsGetHandler),
    (r"/contributions/post", ContributionsPostHandler),
]
