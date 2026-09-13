"""RED/GREEN: a blocked /web SessionLocal() must not starve /api/health."""

from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from app.middleware.web_session import web_session_gate
from app.routes.web_auth import SESSION_COOKIE_NAME

_BLOCK_SECONDS = 5.0
_HEALTH_BUDGET_SECONDS = 1.0


class _BlockingSession:
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        self._entered = entered
        self._release = release

    def __enter__(self) -> object:
        self._entered.set()
        if not self._release.wait(timeout=_BLOCK_SECONDS + 2):
            raise TimeoutError("auth seam was not released")
        raise AssertionError("blocking session should not continue into SQLAlchemy work")

    def __exit__(self, *_exc: object) -> bool:
        return False


class _SQLAlchemyErrorSession:
    def __enter__(self) -> object:
        raise SQLAlchemyError("injected session failure")

    def __exit__(self, *_exc: object) -> bool:
        return False


@contextmanager
def _running_server() -> Iterator[str]:
    app = FastAPI()
    app.middleware("http")(web_session_gate)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/web")
    def web_home() -> dict[str, bool]:
        return {"ok": True}

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("Uvicorn thread exited before listen")
        if time.monotonic() > deadline:
            raise RuntimeError("Uvicorn did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _web_request(origin: str) -> urllib.request.Request:
    return urllib.request.Request(
        f"{origin}/web",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}=dummy-session"},
    )


def test_blocked_web_session_db_does_not_starve_independent_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        "app.middleware.web_session.SessionLocal",
        lambda: _BlockingSession(entered, release),
    )
    opener = _opener()
    with _running_server() as origin:
        def blocked_auth() -> None:
            try:
                opener.open(_web_request(origin), timeout=_BLOCK_SECONDS + 3)
            except (urllib.error.HTTPError, TimeoutError, OSError):
                return

        auth_thread = threading.Thread(target=blocked_auth, daemon=True)
        auth_thread.start()
        assert entered.wait(timeout=2), "blocked /web auth never entered the DB seam"
        started = time.monotonic()
        with opener.open(
            urllib.request.Request(f"{origin}/api/health"),
            timeout=_HEALTH_BUDGET_SECONDS,
        ) as health:
            elapsed = time.monotonic() - started
            body = health.read()
            status = health.status
        release.set()
        auth_thread.join(timeout=5)

    assert status == 200
    assert b'"status":"ok"' in body.replace(b" ", b"") or b'"status": "ok"' in body
    assert elapsed < _HEALTH_BUDGET_SECONDS, (
        f"independent /api/health took {elapsed:.3f}s while /web auth was blocked; "
        "the Uvicorn event loop was starved"
    )


def test_auth_sqlalchemy_error_is_bounded_and_leaves_health_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.middleware.web_session.SessionLocal",
        _SQLAlchemyErrorSession,
    )
    opener = _opener()
    with _running_server() as origin:
        with pytest.raises(urllib.error.HTTPError) as error:
            opener.open(_web_request(origin), timeout=2)
        started = time.monotonic()
        with opener.open(
            urllib.request.Request(f"{origin}/api/health"),
            timeout=_HEALTH_BUDGET_SECONDS,
        ) as health:
            elapsed = time.monotonic() - started
            status = health.status

    assert error.value.code == 503
    assert status == 200
    assert elapsed < _HEALTH_BUDGET_SECONDS
