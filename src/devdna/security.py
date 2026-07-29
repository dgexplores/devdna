import hashlib
import hmac
import logging
import re
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

CLIENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,48}$")
MINIMUM_API_SECRET_LENGTH = 24
DUMMY_DIGEST = hashlib.sha256(b"invalid-api-key").digest()
RATE_LIMIT_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end
return {current, redis.call("TTL", KEYS[1])}
"""
logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)
BearerCredential = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def parse_api_keys(value: SecretStr | None) -> dict[str, bytes]:
    if value is None or not value.get_secret_value().strip():
        return {}

    credentials: dict[str, bytes] = {}
    for entry in value.get_secret_value().split(","):
        client_id, separator, secret = entry.strip().partition("=")
        if (
            not separator
            or not CLIENT_ID_PATTERN.fullmatch(client_id)
            or len(secret) < MINIMUM_API_SECRET_LENGTH
            or client_id in credentials
        ):
            raise ValueError(
                "DEVDNA_API_KEYS must contain unique client=secret entries "
                f"with {MINIMUM_API_SECRET_LENGTH}-character secrets"
            )
        credentials[client_id] = hashlib.sha256(secret.encode()).digest()
    return credentials


def authenticate_bearer(header: str | None, credentials: dict[str, bytes]) -> str | None:
    if header is None:
        return None
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    client_id, separator, secret = token.partition(".")
    if not separator or not CLIENT_ID_PATTERN.fullmatch(client_id):
        return None

    supplied_digest = hashlib.sha256(secret.encode()).digest()
    expected_digest = credentials.get(client_id, DUMMY_DIGEST)
    if not hmac.compare_digest(supplied_digest, expected_digest):
        return None
    return client_id


async def authorize_analysis_creation(
    request: Request,
    response: Response,
    authorization: BearerCredential,
) -> None:
    api_credentials: dict[str, bytes] = request.app.state.api_credentials
    header = (
        f"{authorization.scheme} {authorization.credentials}" if authorization is not None else None
    )
    client_id = authenticate_bearer(header, api_credentials)
    client_host = request.client.host if request.client else "unknown"
    rate_identity = f"client:{client_id}" if client_id else f"peer:{client_host}"
    key = f"devdna:rate:analysis:{rate_identity}"
    settings = request.app.state.settings
    try:
        result: Any = await request.app.state.rate_limiter.eval(
            RATE_LIMIT_SCRIPT,
            1,
            key,
            settings.analysis_rate_window_seconds,
        )
        current, ttl = int(result[0]), max(1, int(result[1]))
    except Exception as error:
        logger.exception("Analysis rate limiter failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable",
        ) from error

    response.headers["X-RateLimit-Limit"] = str(settings.analysis_rate_limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, settings.analysis_rate_limit - current))
    if current > settings.analysis_rate_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Analysis request limit exceeded",
            headers={
                "X-RateLimit-Limit": str(settings.analysis_rate_limit),
                "X-RateLimit-Remaining": "0",
                "Retry-After": str(ttl),
            },
        )
    if api_credentials and client_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid bearer API key required",
            headers={
                "WWW-Authenticate": "Bearer",
                "X-RateLimit-Limit": str(settings.analysis_rate_limit),
                "X-RateLimit-Remaining": str(settings.analysis_rate_limit - current),
            },
        )
    request.state.api_client_id = client_id
