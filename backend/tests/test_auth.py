import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.auth import AuthService, LoginLimiter
from app.config import Settings, get_settings
from app.main import create_app

PASSPHRASE = "correct horse battery staple"
SECRET = "s" * 40
ORIGIN = "http://localhost:3000"


def _client(monkeypatch: pytest.MonkeyPatch, **extra: str) -> Iterator[TestClient]:
    env = {
        "AUTH_PASSPHRASE": PASSPHRASE,
        "SESSION_SECRET": SECRET,
        "CORS_ORIGINS": json.dumps([ORIGIN]),
        **extra,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        with TestClient(create_app(), base_url=ORIGIN) as client:
            yield client
    finally:
        get_settings.cache_clear()


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from _client(monkeypatch)


def login(client: TestClient, passphrase: str = PASSPHRASE) -> int:
    return client.post("/api/auth/login", json={"passphrase": passphrase}).status_code


# ---- API guard ----


def test_without_a_passphrase_configured_everything_stays_open(client: TestClient) -> None:
    assert client.get("/api/auth/me").json() == {"auth_required": False, "authenticated": True}
    assert client.get("/api/notes").status_code == 200


def test_guarded_routes_need_a_session_but_health_and_status_do_not(
    auth_client: TestClient,
) -> None:
    assert auth_client.get("/healthz").status_code == 200
    assert auth_client.get("/api/auth/me").json() == {
        "auth_required": True,
        "authenticated": False,
    }
    for path in ("/api/notes", "/api/tracks", "/api/graph", "/api/sessions/" + "0" * 32):
        assert auth_client.get(path).status_code == 401, path
    assert auth_client.post("/api/notes", json={"title": "t", "body_md": "b"}).status_code == 401


def test_wrong_passphrase_is_rejected_and_sets_no_cookie(auth_client: TestClient) -> None:
    r = auth_client.post("/api/auth/login", json={"passphrase": "nope"})
    assert r.status_code == 401
    assert "set-cookie" not in r.headers
    assert auth_client.get("/api/notes").status_code == 401


def test_login_sets_a_hardened_cookie_and_unlocks_the_api(auth_client: TestClient) -> None:
    r = auth_client.post("/api/auth/login", json={"passphrase": PASSPHRASE})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "max-age=2592000" in cookie
    assert "secure" not in cookie  # COOKIE_SECURE defaults to false for plain-http localhost
    assert auth_client.get("/api/notes").status_code == 200
    assert auth_client.get("/api/auth/me").json()["authenticated"] is True


def test_cookie_is_secure_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _client(monkeypatch, COOKIE_SECURE="true"):
        r = client.post("/api/auth/login", json={"passphrase": PASSPHRASE})
        assert "secure" in r.headers["set-cookie"].lower()


def test_logout_ends_the_session(auth_client: TestClient) -> None:
    assert login(auth_client) == 200
    assert auth_client.post("/api/auth/logout").json()["authenticated"] is False
    assert auth_client.get("/api/notes").status_code == 401


def test_repeated_wrong_passphrases_lock_the_client_out(auth_client: TestClient) -> None:
    for _ in range(5):
        assert login(auth_client, "wrong") == 401
    blocked = auth_client.post("/api/auth/login", json={"passphrase": PASSPHRASE})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


def test_a_tampered_cookie_is_rejected(auth_client: TestClient) -> None:
    assert login(auth_client) == 200
    token = auth_client.cookies["recall_session"]
    auth_client.cookies.clear()
    auth_client.cookies.set("recall_session", token[:-3] + "AAA")
    assert auth_client.get("/api/notes").status_code == 401


# ---- WebSocket guard ----


def test_websocket_without_a_session_is_refused(auth_client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        auth_client.websocket_connect("/ws/voice", headers={"origin": ORIGIN}),
    ):
        pass
    assert exc.value.code == 4401


def test_websocket_works_after_login_and_refuses_foreign_origins(auth_client: TestClient) -> None:
    assert login(auth_client) == 200
    cookie = f"recall_session={auth_client.cookies['recall_session']}"
    with auth_client.websocket_connect(
        "/ws/voice", headers={"origin": ORIGIN, "cookie": cookie}
    ) as ws:
        ws.send_text(json.dumps({"type": "start", "track": "ai-eng"}))
        assert ws.receive_json()["type"] == "session"

    with (
        pytest.raises(WebSocketDisconnect) as exc,
        auth_client.websocket_connect("/ws/voice", headers={"origin": "https://evil.example"}),
    ):
        pass
    assert exc.value.code == 4403


# ---- units ----


def settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_tokens_expire_and_are_bound_to_the_secret() -> None:
    svc = AuthService(settings(auth_passphrase=PASSPHRASE, session_secret=SECRET))
    token = svc.issue()
    assert svc.verify(token)
    assert not svc.verify(None) and not svc.verify("garbage")
    svc.max_age = -1
    assert not svc.verify(token)
    other = AuthService(settings(auth_passphrase=PASSPHRASE, session_secret="o" * 40))
    assert not other.verify(token)


def test_login_limiter_window_expires() -> None:
    limiter = LoginLimiter(max_failures=2, window_s=100)
    limiter.record_failure("ip", now=0)
    assert limiter.retry_after("ip", now=1) == 0
    limiter.record_failure("ip", now=2)
    assert limiter.retry_after("ip", now=3) == 97
    assert limiter.retry_after("other", now=3) == 0
    assert limiter.retry_after("ip", now=200) == 0
    limiter.record_failure("ip", now=201)
    limiter.reset("ip")
    assert limiter.retry_after("ip", now=202) == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"environment": "production"},
        {"environment": "production", "auth_passphrase": "short"},
        {"environment": "production", "auth_passphrase": PASSPHRASE, "session_secret": SECRET},
        {"auth_passphrase": PASSPHRASE},
        {"auth_passphrase": PASSPHRASE, "session_secret": "too short"},
    ],
)
def test_unsafe_configurations_refuse_to_start(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        settings(**kwargs)


def test_a_complete_production_configuration_is_accepted() -> None:
    s = settings(
        environment="production",
        auth_passphrase=PASSPHRASE,
        session_secret=SECRET,
        cookie_secure=True,
    )
    assert s.environment == "production"
