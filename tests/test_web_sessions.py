import time

import pytest

from devdna.web_sessions import create_web_session, verify_web_session


def test_web_session_round_trip_and_tamper_rejection() -> None:
    token = create_web_session("developer", "a-long-session-secret", 3600)

    assert verify_web_session(token, "a-long-session-secret") == "developer"
    assert verify_web_session(token + "changed", "a-long-session-secret") is None
    assert verify_web_session(token, "different-secret") is None


def test_web_session_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: 1000)
    token = create_web_session("developer", "a-long-session-secret", 10)
    monkeypatch.setattr(time, "time", lambda: 1011)

    assert verify_web_session(token, "a-long-session-secret") is None
