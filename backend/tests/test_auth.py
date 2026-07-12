import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


TEST_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$JJsgtT5z5+neM/k5hS1+jg$"
    "CFAKkq/ZOtKk/e1QiFm/KkEPBxYjw7x+6Sc2RJQsAxw"
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_USERNAME", "owner")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", TEST_PASSWORD_HASH)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-with-32-characters")
    get_settings.cache_clear()

    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client

    get_settings.cache_clear()


def test_login_rejects_invalid_credentials(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"username": "owner", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "INVALID_CREDENTIALS",
            "message": "Username atau password salah.",
        }
    }
    assert "meguyomi_session" not in client.cookies


def test_login_creates_session_and_me_returns_user(client: TestClient) -> None:
    login_response = client.post(
        "/auth/login",
        json={"username": "owner", "password": "test-password"},
    )

    assert login_response.status_code == 200
    assert login_response.json() == {"username": "owner"}
    assert "meguyomi_session" in client.cookies
    cookie_header = login_response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header

    me_response = client.get("/auth/me")
    assert me_response.status_code == 200
    assert me_response.json() == {"username": "owner"}


def test_logout_invalidates_session(client: TestClient) -> None:
    client.post(
        "/auth/login",
        json={"username": "owner", "password": "test-password"},
    )

    logout_response = client.post("/auth/logout")

    assert logout_response.status_code == 204
    assert "meguyomi_session" not in client.cookies
    me_response = client.get("/auth/me")
    assert me_response.status_code == 401
    assert me_response.json() == {
        "error": {
            "code": "NOT_AUTHENTICATED",
            "message": "Sesi login tidak valid.",
        }
    }


def test_login_rate_limits_repeated_failures(client: TestClient) -> None:
    for _ in range(5):
        response = client.post(
            "/auth/login",
            json={"username": "attacker", "password": "wrong-password"},
        )
        assert response.status_code == 401

    blocked_response = client.post(
        "/auth/login",
        json={"username": "attacker", "password": "wrong-password"},
    )

    assert blocked_response.status_code == 429
    assert blocked_response.json() == {
        "error": {
            "code": "RATE_LIMITED",
            "message": "Terlalu banyak percobaan login. Coba lagi nanti.",
        }
    }
