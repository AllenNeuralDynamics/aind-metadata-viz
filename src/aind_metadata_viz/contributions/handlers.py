"""FastAPI router for the contributions REST endpoints.

See /docs (Swagger UI) for full request/response schemas.
"""

import asyncio
import logging
import re
import time
import unicodedata
from typing import Optional
from urllib.parse import urlsplit

import httpx
from aind_data_schema_models.registries import Registry
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

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
from ..auth import config as auth_config
from ..auth import get_current_user

_logger = logging.getLogger(__name__)


contributions_router = APIRouter(tags=["contributions"])
_ORCID_ACCEPT = "application/vnd.orcid+json"
_orcid_public_token = None
_orcid_public_token_expires_at = 0
_orcid_public_token_lock = asyncio.Lock()


def _normalize_orcid(value):
    """Normalize common ORCID URL and punctuation variants for comparison."""
    raw = str(value or "").strip()
    match = re.search(r"orcid\.org/([^/?#]+)", raw, flags=re.IGNORECASE)
    if match:
        raw = match.group(1)
    raw = raw.strip("/")
    compact = re.sub(r"[\s-]", "", raw).upper()
    if re.fullmatch(r"\d{15}[\dX]", compact):
        return f"{compact[:4]}-{compact[4:8]}-{compact[8:12]}-{compact[12:]}"
    return raw


def _owned_name(existing, orcid):
    """Return the contributor name linked to *orcid*, if one exists.

    Display names are never proof of ownership; unlinked records must be
    explicitly linked before the author endpoint can edit them.
    """
    if existing is None or not orcid:
        return None
    for c in existing.contributors:
        stored_orcid = _normalize_orcid(getattr(c.author, "registry_identifier", None))
        if stored_orcid and stored_orcid == _normalize_orcid(orcid):
            return c.author.name
    return None


def _normalize_person_name(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[’'`]", "", normalized)
    return re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()


def _name_similarity(left, right):
    left = _normalize_person_name(left)
    right = _normalize_person_name(right)
    if not left or not right:
        return 0
    if left == right:
        return 1
    left_sorted = " ".join(sorted(left.split()))
    right_sorted = " ".join(sorted(right.split()))
    tokens_left = left_sorted.split()
    tokens_right = right_sorted.split()
    token_similarity = 0
    if len(tokens_left) == len(tokens_right):
        token_similarity = sum(
            0.9
            if min(len(token), len(other)) == 1 and token[0] == other[0]
            else _edit_similarity(token, other)
            for token, other in zip(tokens_left, tokens_right)
        ) / len(tokens_left)
    return max(
        _edit_similarity(left, right),
        _edit_similarity(left_sorted, right_sorted),
        token_similarity,
    )


def _edit_similarity(left, right):
    if not left or not right:
        return 0
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, 1):
        current = [index]
        for other_index, other_char in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[other_index] + 1,
                previous[other_index - 1] + (char != other_char),
            ))
        previous = current
    return 1 - previous[-1] / max(len(left), len(right))


def _author_name_matches_profile(author, profile_name):
    variants = [author.name, *(author.other_names or [])]
    return any(_name_similarity(variant, profile_name) >= 0.82 for variant in variants)


def _orcid_api_base_url():
    host = urlsplit(auth_config.ORCID_ISSUER).hostname
    if host not in {"orcid.org", "sandbox.orcid.org"}:
        raise RuntimeError("ORCID API issuer is not configured")
    return f"https://pub.{host}"


async def _get_orcid_public_token():
    global _orcid_public_token, _orcid_public_token_expires_at
    if not auth_config.ORCID_CLIENT_ID or not auth_config.ORCID_CLIENT_SECRET:
        raise RuntimeError("ORCID API credentials are not configured")
    if _orcid_public_token and time.monotonic() < _orcid_public_token_expires_at:
        return _orcid_public_token

    async with _orcid_public_token_lock:
        if _orcid_public_token and time.monotonic() < _orcid_public_token_expires_at:
            return _orcid_public_token
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{auth_config.ORCID_ISSUER}/oauth/token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": auth_config.ORCID_CLIENT_ID,
                    "client_secret": auth_config.ORCID_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                    "scope": "/read-public",
                },
            )
        response.raise_for_status()
        token_data = response.json()
        token = token_data.get("access_token")
        if not token:
            raise RuntimeError("ORCID did not return a public-read token")
        expires_in = max(60, int(token_data.get("expires_in") or 3600))
        _orcid_public_token = token
        _orcid_public_token_expires_at = time.monotonic() + expires_in - 30
        return token


async def _orcid_get_json(client, token, path, params=None):
    response = await client.get(
        f"{_orcid_api_base_url()}/v3.0/{path.lstrip('/')}",
        params=params,
        headers={"Accept": _ORCID_ACCEPT, "Authorization": f"Bearer {token}"},
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _orcid_person_name(person):
    root = person.get("person", person) if isinstance(person, dict) else {}
    name = root.get("name") or (root.get("personal-details") or {}).get("name") or {}

    def visible(value):
        return value if isinstance(value, str) else (value or {}).get("value", "")

    return visible(name.get("credit-name")) or " ".join(
        part
        for part in (
            visible(name.get("given-names")),
            visible(name.get("family-name")),
        )
        if part
    )


async def _search_orcid_profiles(name):
    parts = str(name).strip().split()
    family_name = parts[-1]
    given_names = " ".join(parts[:-1])

    def quote(value):
        return value.replace("\\", "\\\\").replace('"', '\\"')

    query = f'family-name:"{quote(family_name)}"'
    if given_names:
        query += f' AND given-names:"{quote(given_names)}"'

    token = await _get_orcid_public_token()
    async with httpx.AsyncClient(timeout=10) as client:
        result = await _orcid_get_json(
            client, token, "search/", params={"q": query, "rows": 5}
        )
        paths = [
            _normalize_orcid((item.get("orcid-identifier") or {}).get("path"))
            for item in (result or {}).get("result", [])
        ]
        identifiers = list(dict.fromkeys(
            path for path in paths
            if re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", path, flags=re.IGNORECASE)
        ))

        async def read_name(orcid):
            try:
                person = await _orcid_get_json(client, token, f"{orcid}/person")
                return {"orcid": orcid, "name": _orcid_person_name(person)}
            except Exception:
                _logger.info("Could not read public ORCID profile %s", orcid)
                return {"orcid": orcid, "name": ""}

        return await asyncio.gather(*(read_name(orcid) for orcid in identifiers))


async def _read_orcid_profile(orcid):
    token = await _get_orcid_public_token()
    async with httpx.AsyncClient(timeout=10) as client:
        person = await _orcid_get_json(client, token, f"{orcid}/person")
    return {"orcid": orcid, "name": _orcid_person_name(person)}


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
        _normalize_orcid(getattr(c.author, "registry_identifier", None)) == _normalize_orcid(orcid)
        and c.is_admin
        for c in contributions.contributors
    )


def _has_admin(contributions):
    """Return True when a contribution document retains at least one admin."""
    return bool(contributions and any(c.is_admin for c in contributions.contributors))


def _merge_author_contribution(existing, orcid, incoming):
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
    owned = _owned_name(existing, orcid)
    incoming_name = incoming.author.name

    if owned is None:
        # Anonymous visitors may append one new author, but cannot overwrite a
        # stored row merely by choosing the same display name.
        if incoming_name in stored_by_name:
            return False, "You can only add a new author entry", None
        row = incoming.model_copy(deep=True)
        row.is_admin = False
        row.author.registry = Registry.ORCID
        row.author.registry_identifier = _normalize_orcid(orcid) if orcid else None
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
        row.author.registry = Registry.ORCID
        row.author.registry_identifier = _normalize_orcid(orcid)
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
    "/contributions/orcid/search",
    summary="Search public ORCID names",
    description=(
        "Returns a small set of public ORCID name matches. ORCID API credentials and "
        "read-public tokens stay on the server."
    ),
)
async def contributions_orcid_search(
    name: str = Query(min_length=1, max_length=200, description="Person name to search"),
):
    if not name.strip():
        return JSONResponse(status_code=400, content={"error": "name is required"})
    try:
        results = await _search_orcid_profiles(name.strip())
    except RuntimeError:
        _logger.exception("GET /contributions/orcid/search: ORCID API is not configured")
        return JSONResponse(
            status_code=503,
            content={"error": "ORCID name search is not configured."},
        )
    except Exception:
        _logger.exception("GET /contributions/orcid/search")
        return JSONResponse(
            status_code=502,
            content={"error": "ORCID search is temporarily unavailable."},
        )
    return JSONResponse(content={"results": results})


@contributions_router.get(
    "/contributions/orcid/profile",
    summary="Read a public ORCID name",
    description="Returns the public name for an ORCID iD when one is available.",
)
async def contributions_orcid_profile(
    orcid: str = Query(description="ORCID iD or profile URL"),
):
    normalized = _normalize_orcid(orcid)
    if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", normalized, flags=re.IGNORECASE):
        return JSONResponse(status_code=400, content={"error": "A valid ORCID iD is required."})
    try:
        profile = await _read_orcid_profile(normalized)
    except RuntimeError:
        _logger.exception("GET /contributions/orcid/profile: ORCID API is not configured")
        return JSONResponse(
            status_code=503,
            content={"error": "ORCID name lookup is not configured."},
        )
    except Exception:
        _logger.exception("GET /contributions/orcid/profile")
        return JSONResponse(
            status_code=502,
            content={"error": "ORCID profile lookup is temporarily unavailable."},
        )
    return JSONResponse(content=profile)


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
    ok, err, merged = await asyncio.to_thread(
        _merge_author_contribution, existing, orcid, incoming
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


@contributions_router.post(
    "/contributions/author/link",
    summary="Link an unlinked contributor to the signed-in ORCID",
    description=(
        "Links one uniquely named, unlinked contributor record to the caller's ORCID. "
        "The record name must match the ORCID profile name or one of its stored aliases."
    ),
)
async def contributions_author_link_post(
    request: Request,
    project: Optional[str] = Query(default=None, description="Existing project name (required)"),
):
    if not project:
        return JSONResponse(
            status_code=400,
            content={"error": "project query parameter is required"},
        )

    user = get_current_user(request)
    if not user:
        return JSONResponse(
            status_code=401,
            content={"error": "Log in with ORCID before linking a contributor record."},
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "request body must be JSON"})
    author_name = body.get("author_name") if isinstance(body, dict) else None
    if not isinstance(author_name, str) or not author_name.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "author_name is required"},
        )
    author_name = author_name.strip()

    try:
        existing = await asyncio.to_thread(get_contributions, project)
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": f"Project '{project}' not found"})
    except Exception as e:
        _logger.exception("POST /contributions/author/link project=%s", project)
        return JSONResponse(status_code=500, content={"error": str(e)})

    user_orcid = _normalize_orcid(user.get("orcid"))
    if not user_orcid:
        return JSONResponse(
            status_code=401,
            content={"error": "The signed-in session has no ORCID iD."},
        )
    session_admin = bool(
        user.get("is_admin") or _is_admin_contributor(existing, user_orcid)
    )
    if existing.edit_locked and not session_admin:
        return JSONResponse(
            status_code=403,
            content={"error": "This project is locked; ask an admin to unlock it before editing."},
        )

    matches = [c for c in existing.contributors if c.author.name == author_name]
    if not matches:
        return JSONResponse(
            status_code=404,
            content={"error": "This contributor record is no longer available."},
        )
    if len(matches) != 1:
        return JSONResponse(
            status_code=409,
            content={"error": "More than one contributor record has this name."},
        )

    target = matches[0]
    if target.author.registry_identifier:
        return JSONResponse(
            status_code=409,
            content={"error": "This contributor record is already linked to an ORCID."},
        )
    if any(
        _normalize_orcid(c.author.registry_identifier) == user_orcid
        for c in existing.contributors
    ):
        return JSONResponse(
            status_code=409,
            content={"error": "Your ORCID is already linked to another contributor record."},
        )
    if target.is_admin and not session_admin:
        return JSONResponse(
            status_code=403,
            content={"error": "Only a project admin can link an admin contributor record."},
        )
    if not _author_name_matches_profile(target.author, user.get("name")):
        return JSONResponse(
            status_code=403,
            content={"error": "This contributor name does not match your ORCID profile."},
        )

    linked = existing.model_copy(deep=True)
    linked_target = next(c for c in linked.contributors if c.author.name == author_name)
    linked_target.author.registry_identifier = user_orcid
    linked_target.author.registry = Registry.ORCID

    try:
        commit_hash = await asyncio.to_thread(
            store_contributions,
            project,
            linked,
            message=f"Link contributor {author_name} to ORCID",
        )
    except Exception as e:
        _logger.exception("POST /contributions/author/link project=%s", project)
        return JSONResponse(status_code=500, content={"error": str(e)})

    return JSONResponse(
        content={"commit": commit_hash, "project": project, "author_name": author_name}
    )


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
