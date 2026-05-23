"""Cloudflare Access JWT verification for the public /web origin boundary."""

from __future__ import annotations

from functools import lru_cache
from typing import Any


class CloudflareAccessVerificationError(Exception):
    """Raised when the Access application token is missing or invalid."""


@lru_cache(maxsize=8)
def _jwk_client(certs_url: str) -> Any:
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - exercised only in misconfigured runtime
        raise CloudflareAccessVerificationError(
            "PyJWT[crypto] is required when CLOUDFLARE_ACCESS_REQUIRED=true."
        ) from exc
    return jwt.PyJWKClient(certs_url)


def verify_cloudflare_access_jwt(
    token: str,
    *,
    team_domain: str,
    audience: str,
) -> dict[str, Any]:
    """Validate a Cloudflare Access application token.

    Cloudflare documents the signing keys at
    ``https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`` and sends
    the application token to origins as ``Cf-Access-Jwt-Assertion``.
    """
    cleaned_token = (token or "").strip()
    cleaned_team_domain = (team_domain or "").strip().rstrip("/")
    cleaned_audience = (audience or "").strip()
    if not cleaned_token or not cleaned_team_domain or not cleaned_audience:
        raise CloudflareAccessVerificationError("Cloudflare Access JWT is not configured.")

    try:
        import jwt

        certs_url = f"{cleaned_team_domain}/cdn-cgi/access/certs"
        signing_key = _jwk_client(certs_url).get_signing_key_from_jwt(cleaned_token)
        claims = jwt.decode(
            cleaned_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=cleaned_audience,
            issuer=cleaned_team_domain,
        )
    except Exception as exc:  # noqa: BLE001 - PyJWT raises several validation subclasses.
        raise CloudflareAccessVerificationError("Cloudflare Access JWT validation failed.") from exc
    if not isinstance(claims, dict):
        raise CloudflareAccessVerificationError("Cloudflare Access JWT claims were invalid.")
    return claims


def reset_cloudflare_access_cache() -> None:
    _jwk_client.cache_clear()
