import base64
import hashlib
import hmac
import time

from devdna.security import CLIENT_ID_PATTERN

SESSION_COOKIE = "devdna_session"


def session_signature(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def create_web_session(client_id: str, secret: str, max_age_seconds: int) -> str:
    if not CLIENT_ID_PATTERN.fullmatch(client_id):
        raise ValueError("invalid session client")
    expires_at = int(time.time()) + max_age_seconds
    payload = f"{client_id}.{expires_at}"
    return f"{payload}.{session_signature(payload, secret)}"


def verify_web_session(value: str | None, secret: str) -> str | None:
    if not value:
        return None
    client_id, separator, remainder = value.partition(".")
    expires_text, signature_separator, supplied_signature = remainder.partition(".")
    if (
        not separator
        or not signature_separator
        or not CLIENT_ID_PATTERN.fullmatch(client_id)
        or not expires_text.isdigit()
    ):
        return None
    payload = f"{client_id}.{expires_text}"
    if not hmac.compare_digest(
        supplied_signature,
        session_signature(payload, secret),
    ):
        return None
    if int(expires_text) < int(time.time()):
        return None
    return client_id
