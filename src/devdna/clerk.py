import logging
from typing import Any

import jwt

from devdna.config import Settings

logger = logging.getLogger(__name__)

Claims = dict[str, Any]

# Cache of Clerk JWKS clients by URL, refreshed on key changes.
_clients: dict[str, jwt.PyJWKClient] = {}


def _jwks_client(settings: Settings) -> jwt.PyJWKClient | None:
    if not settings.clerk_jwks_url:
        return None
    client = _clients.get(settings.clerk_jwks_url)
    if client is None:
        client = jwt.PyJWKClient(
            settings.clerk_jwks_url,
            cache_keys=True,
            lifespan=3600,
        )
        _clients[settings.clerk_jwks_url] = client
    return client


def verify_clerk_token(token: str, settings: Settings) -> Claims | None:
    """Verify a Clerk-issued session JWT and return its claims, or None."""
    client = _jwks_client(settings)
    if client is None or not settings.clerk_issuer:
        return None
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={
                "verify_aud": False,
                "require": ["exp", "iat", "sub"],
            },
        )
    except (jwt.InvalidTokenError, KeyError, TypeError):
        logger.debug("Clerk token verification failed", exc_info=True)
        return None
    if "sub" not in claims:
        return None
    return claims
