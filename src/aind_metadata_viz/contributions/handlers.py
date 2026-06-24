"""FastAPI router for the contributions REST endpoints.

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
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

_logger = logging.getLogger(__name__)

from datetime import datetime, timezone

from . import from_json, from_yaml, get_contributions, list_project_commits, store_contributions, to_json, to_yaml
from .models import ProjectContributions
from .store import (
    consume_token,
    create_token,
    find_active_token,
    get_author_image_key,
    get_contributions_by_doi,
    is_project_locked,
    lookup_token,
    set_project_password,
    verify_project_password,
    _MAX_MULTI_AUTHOR_DAYS,
    _MAX_TOKEN_DAYS,
)


contributions_router = APIRouter()


def _validate_token_scope(project_name, token_type, author_name, new_contributions):
    """Return ``(ok, error_message)`` for token-scoped change validation."""
    try:
        existing = get_contributions(project_name)
    except FileNotFoundError:
        existing = None

    existing_names = {c.author.name for c in existing.contributors} if existing else set()
    new_names = {c.author.name for c in new_contributions.contributors}

    if token_type in ("add_author", "multi_author"):
        removed = existing_names - new_names
        if removed:
            return False, (
                f"{token_type} token cannot remove existing authors: "
                + ", ".join(sorted(removed))
            )
        added = new_names - existing_names
        if len(added) != 1:
            return False, f"{token_type} token allows adding exactly one new author"
        if existing:
            existing_by_name = {c.author.name: c for c in existing.contributors}
            for c in new_contributions.contributors:
                if c.author.name in existing_by_name:
                    if c.model_dump_json() != existing_by_name[c.author.name].model_dump_json():
                        return False, (
                            f"{token_type} token cannot modify existing author '{c.author.name}'"
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
    """Return ``(contributions, project_name)`` for a DOI or project name."""
    try:
        contributions = get_contributions_by_doi(identifier)
        return contributions, contributions.project_name
    except FileNotFoundError:
        pass
    contributions = get_contributions(identifier)
    return contributions, identifier


@contributions_router.get("/contributions/get")
async def contributions_get(request: Request):
    project = request.query_params.get("project", None)
    doi = request.query_params.get("doi", None)

    if not project and not doi:
        return JSONResponse(
            status_code=400,
            content={"error": "project or doi query parameter is required"},
        )

    if doi:
        try:
            contributions, project_name = _resolve_project(doi)
        except FileNotFoundError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except Exception as e:
            _logger.exception("GET /contributions/get doi=%s", doi)
            return JSONResponse(status_code=500, content={"error": str(e)})

        password = request.query_params.get("password", None)
        if not verify_project_password(project_name, password or ""):
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        contributions.locked = is_project_locked(project_name)
        fmt = request.query_params.get("format", "json").lower()
        if fmt == "yaml":
            return Response(content=to_yaml(contributions), media_type="text/plain; charset=utf-8")
        return Response(content=to_json(contributions), media_type="application/json")

    if request.query_params.get("history", None) == "true":
        try:
            commits = list_project_commits(project)
        except FileNotFoundError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except Exception as e:
            _logger.exception("GET /contributions/get history project=%s", project)
            return JSONResponse(status_code=500, content={"error": str(e)})
        return JSONResponse(content=commits)

    commit = request.query_params.get("commit", None)
    fmt = request.query_params.get("format", "json").lower()

    try:
        contributions = get_contributions(project, commit_hash=commit)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:
        _logger.exception("GET /contributions/get project=%s commit=%s", project, commit)
        return JSONResponse(status_code=500, content={"error": str(e)})

    contributions.locked = is_project_locked(project)
    if fmt == "yaml":
        return Response(content=to_yaml(contributions), media_type="text/plain; charset=utf-8")
    return Response(content=to_json(contributions), media_type="application/json")


@contributions_router.post("/contributions/post")
async def contributions_post(request: Request):
    project = request.query_params.get("project", None)
    if not project:
        return JSONResponse(
            status_code=400,
            content={"error": "project query parameter is required"},
        )

    body = await request.body()
    if not body:
        return JSONResponse(status_code=400, content={"error": "request body is required"})

    try:
        data = body.decode("utf-8")
        stripped = data.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            new_contributions = from_json(stripped)
        else:
            new_contributions = from_yaml(stripped)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Failed to parse body: {e}"})

    password = request.query_params.get("password", None)
    token_id = None
    token_type = None
    new_author_name = None

    if password:
        token_record = lookup_token(project, password)
        if token_record is not None:
            token_id = password
            token_type = token_record["token_type"]
            token_author = token_record.get("author_name")
            ok, err = _validate_token_scope(project, token_type, token_author, new_contributions)
            if not ok:
                return JSONResponse(status_code=403, content={"error": err})
            if token_type in ("add_author", "multi_author"):
                try:
                    existing_pre = get_contributions(project)
                    existing_names_pre = {c.author.name for c in existing_pre.contributors}
                except FileNotFoundError:
                    existing_names_pre = set()
                added = {c.author.name for c in new_contributions.contributors} - existing_names_pre
                if len(added) == 1:
                    new_author_name = next(iter(added))
        else:
            if not verify_project_password(project, password):
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    else:
        if not verify_project_password(project, ""):
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    if password and token_id is None and not is_project_locked(project):
        set_project_password(project, password)

    message = request.query_params.get("message", None)

    try:
        commit_hash = store_contributions(project, new_contributions, message=message)
    except Exception as e:
        _logger.exception("POST /contributions/post project=%s", project)
        return JSONResponse(status_code=500, content={"error": str(e)})

    if token_id and token_type == "add_author":
        consume_token(project, token_id)

    response_body = {"commit": commit_hash, "project": project}

    if new_author_name:
        try:
            existing_edit = find_active_token(project, "edit_author", author_name=new_author_name)
        except Exception:
            _logger.exception(
                "POST /contributions/post find_active_token project=%s author=%s",
                project,
                new_author_name,
            )
            existing_edit = None
        try:
            if existing_edit is not None:
                edit_token = existing_edit["token_id"]
            else:
                edit_token = create_token(
                    project,
                    "edit_author",
                    author_name=new_author_name,
                    expires_days=_MAX_TOKEN_DAYS,
                )
            response_body["edit_token"] = edit_token
            response_body["edit_author"] = new_author_name
        except Exception:
            _logger.exception(
                "POST /contributions/post create_token project=%s author=%s",
                project,
                new_author_name,
            )

    return JSONResponse(content=response_body)


@contributions_router.get("/contributions/token")
async def contributions_token(request: Request):
    doi = request.query_params.get("doi", None)
    if not doi:
        return JSONResponse(status_code=400, content={"error": "doi query parameter is required"})

    token_type = request.query_params.get("type", None)
    if token_type not in ("add_author", "edit_author", "multi_author"):
        return JSONResponse(
            status_code=400,
            content={"error": "type must be 'add_author', 'edit_author', or 'multi_author'"},
        )

    author = request.query_params.get("author", None)
    if token_type == "edit_author" and not author:
        return JSONResponse(
            status_code=400,
            content={"error": "author parameter is required for edit_author tokens"},
        )

    days_str = request.query_params.get("days", "365")
    try:
        days = int(days_str)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "days must be an integer"})

    try:
        _, project_name = _resolve_project(doi)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:
        _logger.exception("GET /contributions/token doi=%s", doi)
        return JSONResponse(status_code=500, content={"error": str(e)})

    password = request.query_params.get("password", None)
    if not verify_project_password(project_name, password or ""):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    if token_type == "edit_author":
        try:
            existing = find_active_token(project_name, "edit_author", author_name=author)
        except Exception:
            _logger.exception(
                "GET /contributions/token find_active_token project=%s author=%s",
                project_name,
                author,
            )
            existing = None
        if existing is not None:
            try:
                remaining = datetime.fromisoformat(existing["expires_at"]) - datetime.now(timezone.utc)
                remaining_days = max(1, remaining.days)
            except (KeyError, ValueError):
                remaining_days = days
            return JSONResponse(
                content={
                    "token": existing["token_id"],
                    "type": token_type,
                    "expires_days": remaining_days,
                    "reused": True,
                }
            )

    try:
        token_id = create_token(project_name, token_type, author_name=author, expires_days=days)
    except Exception as e:
        _logger.exception("GET /contributions/token create_token project=%s type=%s", project_name, token_type)
        return JSONResponse(status_code=500, content={"error": str(e)})

    capped_days = min(days, _MAX_MULTI_AUTHOR_DAYS if token_type == "multi_author" else 365)
    return JSONResponse(content={"token": token_id, "type": token_type, "expires_days": capped_days})


@contributions_router.get("/contributions/author-image")
async def contributions_author_image(request: Request):
    author = request.query_params.get("author", None)
    if not author:
        return JSONResponse(status_code=400, content={"error": "author query parameter is required"})
    key = get_author_image_key(author)
    if key is None:
        return JSONResponse(status_code=404, content={"error": f"No image found for author '{author}'"})
    return JSONResponse(content={"author": author, "image_key": key})


CONTRIBUTION_ROUTES = contributions_router
