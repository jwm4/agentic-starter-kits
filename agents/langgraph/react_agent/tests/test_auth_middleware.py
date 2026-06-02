from __future__ import annotations

from types import SimpleNamespace

import pytest
from agent_auth.middleware import SATokenAuthMiddleware
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


async def _health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def _chat(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _build_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth_enabled: str = "true",
    allowlist: str = "ci-testing:allowed-caller",
) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", auth_enabled)
    monkeypatch.setenv("AUTH_AUDIENCE", "langgraph-react-agent")
    monkeypatch.setenv("AUTH_EXCLUDE_PATHS", "/health")
    monkeypatch.setenv("AUTH_ALLOWED_SERVICEACCOUNTS", allowlist)

    app = Starlette(
        routes=[
            Route("/health", _health),
            Route("/chat/completions", _chat, methods=["POST"]),
        ]
    )
    app.add_middleware(SATokenAuthMiddleware)
    return TestClient(app)


def _review(username: str, *, authenticated: bool = True):
    return SimpleNamespace(
        status=SimpleNamespace(
            authenticated=authenticated,
            user=SimpleNamespace(username=username),
        )
    )


def test_auth_disabled_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    with _build_client(monkeypatch, auth_enabled="false") as client:
        response = client.post("/chat/completions", json={"messages": []})
    assert response.status_code == 200


def test_health_path_bypasses_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    with _build_client(monkeypatch) as client:
        response = client.get("/health")
    assert response.status_code == 200


def test_missing_bearer_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    with _build_client(monkeypatch) as client:
        response = client.post("/chat/completions", json={"messages": []})
    assert response.status_code == 401


def test_invalid_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SATokenAuthMiddleware, "_validate_token", lambda *_: None)
    with _build_client(monkeypatch) as client:
        response = client.post(
            "/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer invalid"},
        )
    assert response.status_code == 401


def test_allowlisted_serviceaccount_returns_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SATokenAuthMiddleware,
        "_validate_token",
        lambda *_: _review("system:serviceaccount:ci-testing:allowed-caller"),
    )
    with _build_client(monkeypatch) as client:
        response = client.post(
            "/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer good-token"},
        )
    assert response.status_code == 200


def test_non_allowlisted_serviceaccount_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SATokenAuthMiddleware,
        "_validate_token",
        lambda *_: _review("system:serviceaccount:ci-testing:blocked-caller"),
    )
    with _build_client(monkeypatch) as client:
        response = client.post(
            "/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer good-token"},
        )
    assert response.status_code == 403


def test_tokenreview_failure_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_):
        raise RuntimeError("token review unavailable")

    monkeypatch.setattr(SATokenAuthMiddleware, "_validate_token", _raise)
    with _build_client(monkeypatch) as client:
        response = client.post(
            "/chat/completions",
            json={"messages": []},
            headers={"Authorization": "Bearer good-token"},
        )
    assert response.status_code == 503
