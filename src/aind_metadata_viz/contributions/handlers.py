"""FastAPI router for the contributions REST endpoints.

See /docs (Swagger UI) for full request/response schemas.
"""

import asyncio
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

_logger = logging.getLogger(__name__)

from typing import Optional

from . import (
    AuthorContribution,
    from_json,
    from_yaml,
    get_contributions,
    list_all_projects,
    list_project_commits,
    store_contributions,
    to_json,
    to_yaml,
)
from .store import (
    get_author_image_key,
    get_contributions_by_doi,
)
from ..auth import get_current_user


contributions_router = APIRouter(tags=["contributions"])


def _owned_name(existing, orcid, name):
    """Return the name of the contributor that belongs to *orcid*/*name*.

    Matches by ORCID (``author.registry_identifier``) first, then by display
    name. Returns None if the user has no row yet (they are adding it).
    """
    if existing is None:
        return None
    for c in existing.contributors:
        if orcid and getattr(c.author, "registry_identifier", None) == orcid:
            return c.author.name
    if name:
        for c in existing.contributors:
            if c.author.name == name:
                return c.author.name
    return None


def _is_admin_contributor(contributions, orcid):
    """Return True if *orcid* owns a contributor row flagged ``is_admin``.

    Project admins are recorded directly on the contributor metadata: a row
    whose ``author.registry_identifier`` matches the logged-in ORCID and whose
    ``is_admin`` is True. This is the only per-project edit-access state; there
    is no separate membership store.
    """
    if contributions is None or not orcid:
        return False
    return any(
        getattr(c.author, "registry_identifier", None) == orcid and c.is_admin
        for c in contributions.contributors
    )


def _has_admin(contributions):
    """Return True when a contribution document retains at least one admin."""
    return bool(contributions and any(c.is_admin for c in contributions.contributors))


def _merge_author_contribution(existing, orcid, name, incoming):
    """Merge one author-scoped update into the stored project.

    The author endpoint deliberately accepts exactly one contributor, not a
    client-produced copy of the project. Every project-level field and every
    contributor other than the caller's own row therefore comes from storage.
    Admin-owned row fields are also authoritative in storage, so an author
    update cannot grant admin access or clear byline/provenance metadata.
    """
    if existing is None:
        return False, "The project does not exist", None

    stored_by_name = {c.author.name: c for c in existing.contributors}
    owned = _owned_name(existing, orcid, name)
    incoming_name = incoming.author.name

    if owned is None:
        # Anonymous visitors may append one new author, but cannot overwrite a
        # stored row merely by choosing the same display name.
        if incoming_name in stored_by_name:
            return False, "You can only add a new author entry", None
        row = incoming.model_copy(deep=True)
        row.is_admin = False
        merged = existing.model_copy(deep=True)
        merged.contributors = [*existing.contributors, row]
        return True, None, merged

    if incoming_name != owned and incoming_name in stored_by_name:
        return False, "That author name is already used by another contributor", None

    merged_rows = []
    for stored in existing.contributors:
        if stored.author.name != owned:
            merged_rows.append(stored)
            continue

        row = incoming.model_copy(deep=True)
        row.is_admin = stored.is_admin
        row.publication_order = stored.publication_order
        row.author_level = stored.author_level
        row.from_asset = stored.from_asset
        merged_rows.append(row)

    merged = existing.model_copy(deep=True)
    merged.contributors = merged_rows
    return True, None, merged


def _resolve_project(identifier):
    """Return ``(contributions, project_name)`` for a DOI or project name."""
    try:
        contributions = get_contributions_by_doi(identifier)
        return contributions, contributions.project_name
    except FileNotFoundError:
        pass
    contributions = get_contributions(identifier)
    return contributions, identifier


@contributions_router.get(
    "/contributions/projects",
    summary="List all current project names",
    description=(
        "Returns the sorted list of all project names that have contribution "
        "data, as a JSON array of strings. Useful for autocomplete / fuzzy "
        "matching of user-typed project names."
    ),
)
async def contributions_projects():
    try:
        names = await asyncio.to_thread(list_all_projects)
    except Exception as e:
        _logger.exception("GET /contributions/projects")
        return JSONResponse(status_code=500, content={"error": str(e)})
    return JSONResponse(content=names)


@contributions_router.get(
    "/contributions/project",
    summary="Fetch contribution data for a project",
    description=(
        "Returns the latest (or a specific) contribution data for a project. All models are "
        "publicly readable. Lookup by `project` name or by `doi` (falls back "
        "to treating the DOI value as a project name). Pass `history=true` to instead return the "
        "commit history (newest first) as `[{\"commit\", \"timestamp\"}, ...]`, or "
        "`commit=<hash>` to fetch a specific historical version."
    ),
)
async def contributions_project_get(
    project: Optional[str] = Query(default=None, description="Project name to fetch"),
    doi: Optional[str] = Query(default=None, description="Look up a project by DOI instead of name"),
    history: Optional[str] = Query(
        default=None, description="Pass 'true' to return commit history instead of content"
    ),
    commit: Optional[str] = Query(default=None, description="Fetch a specific historical commit hash"),
    format: str = Query(default="json", description="Response format: 'json' or 'yaml'"),
):
    if not project and not doi:
        return JSONResponse(
            status_code=400,
            content={"error": "project or doi query parameter is required"},
        )

    if doi:
        try:
            contributions, project_name = await asyncio.to_thread(_resolve_project, doi)
        except FileNotFoundError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except Exception as e:
            _logger.exception("GET /contributions/project doi=%s", doi)
            return JSONResponse(status_code=500, content={"error": str(e)})

        fmt = format.lower()
        if fmt == "yaml":
            return Response(content=to_yaml(contributions), media_type="text/plain; charset=utf-8")
        return Response(content=to_json(contributions), media_type="application/json")

    if history == "true":
        try:
            commits = await asyncio.to_thread(list_project_commits, project)
        except FileNotFoundError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except Exception as e:
            _logger.exception("GET /contributions/project history project=%s", project)
            return JSONResponse(status_code=500, content={"error": str(e)})
        return JSONResponse(content=commits)

    fmt = format.lower()

    try:
        contributions = await asyncio.to_thread(get_contributions, project, commit_hash=commit)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:
        _logger.exception("GET /contributions/project project=%s commit=%s", project, commit)
        return JSONResponse(status_code=500, content={"error": str(e)})

    if fmt == "yaml":
        return Response(content=to_yaml(contributions), media_type="text/plain; charset=utf-8")
    return Response(content=to_json(contributions), media_type="application/json")


@contributions_router.post(
    "/contributions/project",
    summary="Store a full project contribution edit",
    description=(
        "Body is a complete JSON or YAML ProjectContributions document. Stores a new versioned "
        "commit and returns the commit hash. This endpoint is reserved for the full editor: an "
        "existing project requires a global or project-admin ORCID session. A logged-in creator "
        "may create a new project and is made its first admin. At least one project admin must "
        "be present in the stored document."
    ),
)
async def contributions_project_post(
    request: Request,
    project: Optional[str] = Query(default=None, description="Project name (required; 400 if missing)"),
    message: Optional[str] = Query(default=None, description="Optional commit message"),
):
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

    try:
        existing = await asyncio.to_thread(get_contributions, project)
    except FileNotFoundError:
        existing = None

    # A logged-in ORCID user is a full admin when they are a global admin or a
    # contributor flagged is_admin on this project.
    session_user = get_current_user(request)
    session_admin = bool(
        session_user
        and (session_user["is_admin"] or _is_admin_contributor(existing, session_user["orcid"]))
    )

    # Admin edit lock: when set, only an admin may write (to edit or to unlock).
    if existing is not None and existing.edit_locked and not session_admin:
        return JSONResponse(
            status_code=403,
            content={"error": "This project is locked; ask an admin to unlock it before editing."},
        )

    if existing is None and session_user:
        # Brand-new project: the logged-in creator owns it. Force their own
        # row to is_admin so they (and only they) can manage it afterwards.
        creator_orcid = session_user["orcid"]
        for c in new_contributions.contributors:
            rid = getattr(c.author, "registry_identifier", None)
            c.is_admin = bool(rid and rid == creator_orcid)
    elif existing is None:
        return JSONResponse(
            status_code=401,
            content={"error": "Log in with ORCID to create a new project."},
        )
    elif not session_admin:
        return JSONResponse(
            status_code=403,
            content={"error": "Full project edits require a project admin."},
        )

    to_store = new_contributions

    if not _has_admin(to_store):
        return JSONResponse(
            status_code=400,
            content={"error": "At least one project admin is required."},
        )

    try:
        commit_hash = await asyncio.to_thread(store_contributions, project, to_store, message=message)
    except Exception as e:
        _logger.exception("POST /contributions/project project=%s", project)
        return JSONResponse(status_code=500, content={"error": str(e)})

    return JSONResponse(content={"commit": commit_hash, "project": project})


@contributions_router.post(
    "/contributions/author",
    summary="Store one author-scoped contribution update",
    description=(
        "Body is one AuthorContribution JSON object. The server merges that author into the "
        "stored project and ignores client copies of every other author and project-level field. "
        "A logged-in caller may add or edit only their own row; an anonymous caller may append one "
        "new row. Project admins are preserved by the server, and a locked project still requires "
        "an admin session."
    ),
)
async def contributions_author_post(
    request: Request,
    project: Optional[str] = Query(default=None, description="Existing project name (required)"),
    message: Optional[str] = Query(default=None, description="Optional commit message"),
):
    if not project:
        return JSONResponse(
            status_code=400,
            content={"error": "project query parameter is required"},
        )

    body = await request.body()
    if not body:
        return JSONResponse(status_code=400, content={"error": "request body is required"})

    try:
        incoming = AuthorContribution.model_validate_json(body.decode("utf-8"))
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Failed to parse author body: {e}"})

    try:
        existing = await asyncio.to_thread(get_contributions, project)
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": f"Project '{project}' not found"})
    except Exception as e:
        _logger.exception("POST /contributions/author project=%s", project)
        return JSONResponse(status_code=500, content={"error": str(e)})

    session_user = get_current_user(request)
    session_admin = bool(
        session_user
        and (session_user["is_admin"] or _is_admin_contributor(existing, session_user["orcid"]))
    )

    if existing.edit_locked and not session_admin:
        return JSONResponse(
            status_code=403,
            content={"error": "This project is locked; ask an admin to unlock it before editing."},
        )

    orcid = session_user["orcid"] if session_user else None
    name = session_user.get("name") if session_user else None
    ok, err, merged = await asyncio.to_thread(
        _merge_author_contribution, existing, orcid, name, incoming
    )
    if not ok:
        return JSONResponse(status_code=403, content={"error": err})

    if not _has_admin(merged):
        return JSONResponse(
            status_code=400,
            content={"error": "At least one project admin is required."},
        )

    try:
        commit_hash = await asyncio.to_thread(store_contributions, project, merged, message=message)
    except Exception as e:
        _logger.exception("POST /contributions/author project=%s", project)
        return JSONResponse(status_code=500, content={"error": str(e)})

    return JSONResponse(content={"commit": commit_hash, "project": project})


@contributions_router.get(
    "/contributions/access",
    summary="Whether the current user can edit a project",
    description=(
        "Returns ``{logged_in, is_admin, can_edit}`` for the current session "
        "user relative to ``project``. ``is_admin`` is true for global admins "
        "and for a user whose ORCID matches a contributor row flagged "
        "``is_admin``; those users get the full editor. ``can_edit`` is true "
        "for any logged-in user, since anyone may add or edit their own author "
        "row via the add wizard."
    ),
)
async def contributions_access(
    request: Request,
    project: Optional[str] = Query(default=None, description="Project name"),
):
    user = get_current_user(request)
    if user is None:
        return JSONResponse(
            content={"logged_in": False, "is_admin": False, "can_edit": False}
        )

    is_admin = bool(user["is_admin"])
    if project and not is_admin:
        try:
            existing = await asyncio.to_thread(get_contributions, project)
        except FileNotFoundError:
            existing = None
        except Exception:
            _logger.exception("GET /contributions/access project=%s", project)
            existing = None
        is_admin = _is_admin_contributor(existing, user["orcid"])

    return JSONResponse(
        content={
            "logged_in": True,
            "is_admin": is_admin,
            # Any logged-in user may add/edit their own author row.
            "can_edit": True,
        }
    )


@contributions_router.get(
    "/contributions/author-image",
    summary="Get an author's headshot S3 key",
    description="Returns `{\"author\", \"image_key\"}` for the author's headshot; 404 if not found.",
)
async def contributions_author_image(
    author: Optional[str] = Query(default=None, description="Author name (required; 400 if missing)"),
):
    if not author:
        return JSONResponse(status_code=400, content={"error": "author query parameter is required"})
    key = await asyncio.to_thread(get_author_image_key, author)
    if key is None:
        return JSONResponse(status_code=404, content={"error": f"No image found for author '{author}'"})
    return JSONResponse(content={"author": author, "image_key": key})


CONTRIBUTION_ROUTES = contributions_router
