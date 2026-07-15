"""ORCID OpenID Connect client (Authorization Code flow).

Uses Authlib's Starlette integration to perform the standard OIDC dance:
redirect the user to ORCID's authorize endpoint, then exchange the returned
authorization ``code`` for an ``id_token`` (a signed JWT) which is validated
against ORCID's JWKS. The ``sub`` claim of the id_token is the user's ORCID iD.

The client is registered lazily from ORCID's discovery document so the same
code works against the production issuer or any other configured issuer.
"""

from authlib.integrations.starlette_client import OAuth

from . import config

_oauth = OAuth()
_registered = False


def _ensure_registered() -> None:
    """Register the ORCID OAuth client once, from its discovery document."""
    global _registered
    if _registered:
        return
    _oauth.register(
        name="orcid",
        client_id=config.ORCID_CLIENT_ID,
        client_secret=config.ORCID_CLIENT_SECRET,
        server_metadata_url=config.ORCID_METADATA_URL,
        client_kwargs={"scope": "openid"},
    )
    _registered = True


def client():
    """Return the registered ORCID OAuth client."""
    _ensure_registered()
    return _oauth.orcid


async def authorize_redirect(request, redirect_uri):
    """Return a redirect response sending the user to ORCID to authenticate."""
    return await client().authorize_redirect(request, redirect_uri)


async def fetch_user(request) -> dict:
    """Complete the callback: exchange the code and return the ORCID identity.

    Returns a dict ``{"orcid": <iD>, "name": <display name or None>}``.
    Raises if the exchange or token validation fails.
    """
    token = await client().authorize_access_token(request)
    userinfo = token.get("userinfo") or {}
    orcid = userinfo.get("sub")
    if not orcid:
        raise ValueError("ORCID id_token did not contain a 'sub' claim")
    name = (
        userinfo.get("name")
        or " ".join(
            p
            for p in (
                userinfo.get("given_name"),
                userinfo.get("family_name"),
            )
            if p
        )
        or None
    )
    return {"orcid": orcid, "name": name}
