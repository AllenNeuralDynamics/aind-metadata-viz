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


def _merge_scoped_contributions(existing, orcid, name, new_contributions):
    """Return ``(ok, error, merged)`` for a non-admin / anonymous save.

    The caller may only add their own new author row, or edit the row they own
    (matched by ORCID, else by name). Everyone else's rows — plus every row's
    ``is_admin`` flag and the project ``edit_locked`` flag — are taken
    authoritatively from *existing*; whatever the client sent for those rows is
    ignored. The add wizard resubmits the whole contributor list rebuilt from a
    lossy in-memory form, so comparing the client's copy of untouched rows
    against storage would spuriously reject a legitimate self-add/edit. Building
    the result from storage instead makes it impossible to clobber another row
    (rather than merely rejecting when the round-trip happens to differ).

    ``existing`` must not be None (creating a new project requires an admin
    session, handled by the caller before this point).
    """
    stored_by_name = {c.author.name: c for c in existing.contributors}
    existing_names = set(stored_by_name)
    new_by_name = {c.author.name: c for c in new_contributions.contributors}
    new_names = set(new_by_name)

    owned = _owned_name(existing, orcid, name)  # None for an anonymous caller

    # May not remove anyone else's row (removing your own is allowed).
    removed = existing_names - new_names
    illegal_removed = removed - ({owned} if owned else set())
    if illegal_removed:
        return False, (
            "You can only edit your own author entry; cannot remove: "
            + ", ".join(sorted(illegal_removed))
        ), None

    # May introduce at most one new row (their own).
    added = new_names - existing_names
    if len(added) > 1:
        return False, "You can only add your own author entry", None

    # Build the final list authoritatively from storage.
    merged_rows = []
    for c in existing.contributors:
        nm = c.author.name
        if nm == owned:
            # The caller owns this row and may edit it; keep the stored
            # is_admin flag (non-admins cannot change admin access).
            if nm in new_by_name:
                row = new_by_name[nm].model_copy(deep=True)
                row.is_admin = c.is_admin
                merged_rows.append(row)
            # else: they removed their own row — drop it.
        else:
            # Someone else's row: take it verbatim from storage.
            merged_rows.append(c)

    # Append their new row, if any (never with admin rights).
    for nm in added:
        row = new_by_name[nm].model_copy(deep=True)
        row.is_admin = False
        merged_rows.append(row)

    merged = new_contributions.model_copy(deep=True)
    merged.contributors = merged_rows
    merged.edit_locked = existing.edit_locked  # non-admins cannot change the lock
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
    # What actually gets stored. Admins store their payload verbatim; scoped
    # (non-admin / anonymous) callers get a server-built merge (see below).
    to_store = new_contributions

    if session_user and existing is None:
        # Brand-new project: the logged-in creator owns it. Force their own
        # row to is_admin so they (and only they) can manage it afterwards.
        creator_orcid = session_user["orcid"]
        for c in new_contributions.contributors:
            rid = getattr(c.author, "registry_identifier", None)
            c.is_admin = bool(rid and rid == creator_orcid)
        authed_via_session = True
    elif session_admin:
        authed_via_session = True

    if not authed_via_session:
        # Creating a brand-new project requires an ORCID login: the creator is
        # recorded as an admin (handled above), so a caller who is neither an
        # admin nor logged-in may only add to a project that already exists.
        if existing is None:
            return JSONResponse(
                status_code=401,
                content={"error": "Log in with ORCID to create a new project."},
            )
        # Scoped write: a logged-in non-admin (identified by ORCID/name) or an
        # anonymous visitor (no identity). They may add their own row or edit
        # the row they own; all other rows come from storage untouched.
        orcid = session_user["orcid"] if session_user else None
        name = session_user.get("name") if session_user else None
        ok, err, merged = await asyncio.to_thread(
            _merge_scoped_contributions, existing, orcid, name, new_contributions
        )
        if not ok:
            return JSONResponse(status_code=403, content={"error": err})
        to_store = merged

    try:
        commit_hash = await asyncio.to_thread(store_contributions, project, to_store, message=message)
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
