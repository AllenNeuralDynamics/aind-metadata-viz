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


def _validate_own_row_scope(project_name, orcid, name, new_contributions):
    """Return ``(ok, error)`` for a non-admin logged-in user's save.

    A non-admin may only add or modify *their own* contributor row (matched by
    ORCID or name); every other author must be left unchanged, and they may not
    grant themselves admin.
    """
    try:
        existing = get_contributions(project_name)
    except FileNotFoundError:
        existing = None

    owned = _owned_name(existing, orcid, name)
    existing_by_name = (
        {c.author.name: c for c in existing.contributors} if existing else {}
    )
    existing_names = set(existing_by_name)
    new_names = {c.author.name for c in new_contributions.contributors}

    removed = existing_names - new_names
    if owned in removed:
        removed = removed - {owned}
    if removed:
        return False, (
            "You can only edit your own author entry; cannot remove: "
            + ", ".join(sorted(removed))
        )

    added = new_names - existing_names
    if len(added) > 1:
        return False, "You can only add your own author entry"

    # Non-admins can never change the project edit lock.
    prev_locked = bool(existing.edit_locked) if existing else False
    if bool(new_contributions.edit_locked) != prev_locked:
        return False, "Only a project admin can lock or unlock the project"

    # Non-admins can never introduce or change an is_admin flag: each row's
    # is_admin must equal its previously stored value (False for new rows).
    for c in new_contributions.contributors:
        prev = existing_by_name.get(c.author.name)
        prev_admin = bool(prev.is_admin) if prev else False
        if bool(c.is_admin) != prev_admin:
            return False, "Only a project admin can grant or change admin access"

    for c in new_contributions.contributors:
        if c.author.name == owned:
            continue
        if c.author.name in added:
            # The single new row must be the user's own.
            continue
        old = existing_by_name.get(c.author.name)
        if old and c.model_dump_json() != old.model_dump_json():
            return False, (
                f"You can only edit your own author entry, not '{c.author.name}'"
            )
    return True, None


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
    "/contributions/get",
    summary="Fetch contribution data for a project",
    description=(
        "Returns the latest (or a specific) contribution data for a project. All models are "
        "publicly readable. Lookup by `project` name or by `doi` (falls back "
        "to treating the DOI value as a project name). Pass `history=true` to instead return the "
        "commit history (newest first) as `[{\"commit\", \"timestamp\"}, ...]`, or "
        "`commit=<hash>` to fetch a specific historical version."
    ),
)
async def contributions_get(
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
            _logger.exception("GET /contributions/get doi=%s", doi)
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
            _logger.exception("GET /contributions/get history project=%s", project)
            return JSONResponse(status_code=500, content={"error": str(e)})
        return JSONResponse(content=commits)

    fmt = format.lower()

    try:
        contributions = await asyncio.to_thread(get_contributions, project, commit_hash=commit)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:
        _logger.exception("GET /contributions/get project=%s commit=%s", project, commit)
        return JSONResponse(status_code=500, content={"error": str(e)})

    if fmt == "yaml":
        return Response(content=to_yaml(contributions), media_type="text/plain; charset=utf-8")
    return Response(content=to_json(contributions), media_type="application/json")


@contributions_router.post(
    "/contributions/post",
    summary="Store a new version of a project's contribution data",
    description=(
        "Body is a JSON or YAML string of contribution data (sniffed automatically). Stores a new "
        "versioned commit and returns the commit hash. Auth is by ORCID session: global/project "
        "admins may edit the whole project, while any other caller (logged-in or anonymous) may "
        "only add or modify their own author row. If the project is `edit_locked`, only an admin "
        "may write (403 otherwise)."
    ),
)
async def contributions_post(
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

    authed_via_session = False

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

    # Edit access is derived entirely from the contributor metadata:
    #   * Global admins (ADMIN_ORCIDS) and project admins (a contributor row
    #     matching this ORCID with is_admin=True) may edit the whole project.
    #   * The creator of a brand-new project is made an admin automatically.
    #   * Any other logged-in user may only add/modify their own author row.
    if session_user:
        orcid = session_user["orcid"]
        is_full_admin = session_admin

        if existing is None:
            # Brand-new project: the logged-in creator owns it. Force their own
            # row to is_admin so they (and only they) can manage it afterwards.
            for c in new_contributions.contributors:
                rid = getattr(c.author, "registry_identifier", None)
                c.is_admin = bool(rid and rid == orcid)
            authed_via_session = True
        elif is_full_admin:
            authed_via_session = True
        else:
            # Non-admin: may only add/modify their own author row.
            ok, err = await asyncio.to_thread(
                _validate_own_row_scope,
                project,
                orcid,
                session_user.get("name"),
                new_contributions,
            )
            if not ok:
                return JSONResponse(status_code=403, content={"error": err})
            authed_via_session = True

    if not authed_via_session:
        # Creating a brand-new project requires an ORCID login: the creator is
        # recorded as an admin (handled above in the session branch), so an
        # anonymous caller may only add to a project that already exists.
        if existing is None:
            return JSONResponse(
                status_code=401,
                content={"error": "Log in with ORCID to create a new project."},
            )
        # Anonymous caller on an existing project: no ORCID identity to own a
        # row, so they may only append a single new author entry and may not
        # touch existing rows.
        ok, err = await asyncio.to_thread(
            _validate_own_row_scope, project, None, None, new_contributions
        )
        if not ok:
            return JSONResponse(status_code=403, content={"error": err})

    try:
        commit_hash = await asyncio.to_thread(store_contributions, project, new_contributions, message=message)
    except Exception as e:
        _logger.exception("POST /contributions/post project=%s", project)
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
