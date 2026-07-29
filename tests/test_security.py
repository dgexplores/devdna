import pytest
from pydantic import SecretStr

from devdna.config import Settings
from devdna.main import create_app
from devdna.security import authenticate_bearer, parse_api_keys


def test_production_requires_api_keys() -> None:
    with pytest.raises(ValueError, match="DEVDNA_API_KEYS is required"):
        create_app(Settings(environment="production"))


def test_analysis_authentication_is_declared_in_openapi() -> None:
    schema = create_app(Settings(environment="test")).openapi()

    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert schema["paths"]["/v1/analyses"]["post"]["security"] == [{"HTTPBearer": []}]


def test_parses_and_authenticates_api_keys() -> None:
    credentials = parse_api_keys(
        SecretStr("developer=correct-horse-battery-staple,recruiter=another-long-secret-value")
    )

    assert (
        authenticate_bearer(
            "Bearer developer.correct-horse-battery-staple",
            credentials,
        )
        == "developer"
    )
    assert authenticate_bearer("Bearer developer.wrong-secret-value", credentials) is None
    assert authenticate_bearer("Basic developer.correct-horse-battery-staple", credentials) is None


@pytest.mark.parametrize(
    "value",
    [
        "missing-separator",
        "bad client=correct-horse-battery-staple",
        "developer=short",
        "developer=correct-horse-battery-staple,developer=another-long-secret-value",
    ],
)
def test_rejects_invalid_api_key_configuration(value: str) -> None:
    with pytest.raises(ValueError, match="DEVDNA_API_KEYS"):
        parse_api_keys(SecretStr(value))
