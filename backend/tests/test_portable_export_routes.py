"""Read-authorized portable downloads own their temporary archive until send ends."""

import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_app_context
from app.database import get_db
from app.errors import add_exception_handlers
from app.tenants import AuthContext
from tests.test_original_http_delivery import _deliver

AUTH = AuthContext(account_id=7, account_public_id="account", account_name="Reader",
    ledger_id="reader-ledger", ledger_name="Read ledger", device_id=11,
    device_public_id="device", device_name="Browser", role="viewer", scope="app")


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "private.zip"
    with ZipFile(path, "w") as bundle:
        bundle.writestr("README.txt", "Persisted authorized records; not an installation restore.")
    return SimpleNamespace(path=path, manifest={}, close=Mock(side_effect=path.unlink))


def _app(router):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: Mock()
    add_exception_handlers(app)
    return app


def test_api_portable_requires_identity_and_allows_viewer_without_filters(monkeypatch, archive) -> None:
    from app.routes import exports

    owner = Mock(return_value=archive)
    monkeypatch.setattr(exports, "create_portable_ledger_export", owner)
    app = _app(exports.router)
    with TestClient(app) as client:
        assert client.get("/api/exports/portable").status_code == 401
        owner.assert_not_called()
        app.dependency_overrides[get_current_app_context] = lambda: AUTH
        response = client.get("/api/exports/portable?ledger_id=other&month=1999-01&page=7")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == 'attachment; filename="ticketbox-portable.zip"'
    assert ZipFile(BytesIO(response.content)).read("README.txt").startswith(b"Persisted authorized")
    assert owner.call_args.kwargs["auth"] == AUTH
    assert callable(owner.call_args.kwargs["cancel_requested"])
    archive.close.assert_called_once()
    assert not archive.path.exists()


@pytest.mark.parametrize("surface", ["api", "web"])
def test_download_releases_request_read_before_claiming_snapshot_capacity(monkeypatch, archive, surface):
    from fastapi import Request
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import QueuePool

    from app.routes import exports, web_import_export

    engine = create_engine("sqlite://", poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=0.01)

    def snapshot(db, *, auth, cancel_requested):
        assert callable(cancel_requested)
        with db.get_bind().connect() as connection:
            assert connection.scalar(select(1)) == 1
        return archive

    route = exports if surface == "api" else web_import_export
    monkeypatch.setattr(route, "create_portable_ledger_export", snapshot)
    try:
        with Session(engine) as request_db:
            # Exercise the real pool and Session lifecycle; no product DB schema
            # or snapshot claims. Throttled authentication leaves this read open.
            request_db.execute(select(1))
            request = Request({"type": "http", "method": "GET", "path": f"/{surface}/export/portable"})
            if surface == "api":
                response = exports.export_portable(request, auth=AUTH, db=request_db)
            else:
                request.state.web_session_auth = AUTH
                response = web_import_export.web_export_portable(request, ledger_id=AUTH.ledger_id, db=request_db)
            response.archive.close()
            assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("auth,status", [(None, 401), (AUTH, 200)])
def test_web_portable_uses_actual_selected_session_or_refuses_before_export(monkeypatch, archive, auth, status) -> None:
    from app.routes import web_import_export
    from app.routes.web_common import _require_local

    owner = Mock(return_value=archive)
    monkeypatch.setattr(web_import_export, "create_portable_ledger_export", owner)
    app = _app(web_import_export.router)
    app.dependency_overrides[_require_local] = lambda: None

    @app.middleware("http")
    async def session(request, call_next):
        request.state.web_session_auth = auth
        return await call_next(request)

    with TestClient(app) as client:
        response = client.get("/web/export/portable?ledger_id=other&month=1999-01")
    assert response.status_code == status
    if auth is None:
        owner.assert_not_called()
        assert archive.path.exists()
    else:
        assert owner.call_args.kwargs["auth"] == AUTH
        assert callable(owner.call_args.kwargs["cancel_requested"])
        assert response.headers["cache-control"] == "no-store"
        archive.close.assert_called_once()


@pytest.mark.parametrize("headers,status", [([], 200), ([(b"range", b"bytes=0-3")], 206),
    ([(b"range", b"bytes=999999-")], 416), ([(b"range", b"bad")], 400)])
def test_portable_response_closes_archive_for_stream_and_range_outcomes(archive, headers, status):
    from app.routes._portable_file_response import PortableFileResponse

    messages = asyncio.run(_deliver(PortableFileResponse(archive), headers=headers,
                                   extensions={"http.response.pathsend": {}}))
    assert messages[0]["status"] == status
    assert all(message["type"] != "http.response.pathsend" for message in messages)
    archive.close.assert_called_once()
    assert not archive.path.exists()


@pytest.mark.parametrize("has_session", [False, True])
def test_import_export_page_retains_csv_and_offers_bound_download_or_identity_recovery(monkeypatch, has_session) -> None:
    from pathlib import Path

    from fastapi.templating import Jinja2Templates
    from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

    root = Path(__file__).parents[1] / "app/templates/web"
    templates = Jinja2Templates(directory=root)
    templates.env.loader = ChoiceLoader([DictLoader({"base.html": "{% block content %}{% endblock %}"}),
                                        FileSystemLoader(root)])
    rendered = templates.get_template("import_export.html").render(
        selected_ledger_id=AUTH.ledger_id, selected_ledger_name=AUTH.ledger_name,
        q="?ledger_id=" + AUTH.ledger_id, portable_export_available=has_session, can_write=False,
        batch_page=SimpleNamespace(items=[], page=1, page_size=20, total_pages=1, total=0))
    assert 'action="/web/export.csv"' in rendered
    assert "尚未提交的离线草稿不在包内" in rendered
    assert "不是安装恢复包" in rendered
    assert "你的收件箱和跨账本往来另行标明范围" in rendered and "不带走对方账本的私有记录" in rendered
    if has_session:
        assert f'href="/web/export/portable?ledger_id={AUTH.ledger_id}"' in rendered
        assert "/web/auth/local?next=" not in rendered
    else:
        assert "/web/auth/local?next=" in rendered
        assert 'href="/web/export/portable' not in rendered


@pytest.mark.parametrize("failure", [OSError("disconnected"), asyncio.CancelledError()])
def test_portable_response_closes_archive_on_disconnect_and_cancel(archive, failure):
    from app.routes._portable_file_response import PortableFileResponse

    with pytest.raises(type(failure)):
        asyncio.run(_deliver(PortableFileResponse(archive), fail_send=failure))
    archive.close.assert_called_once()
    assert not archive.path.exists()


def test_portable_request_cancellation_reads_disconnect_from_route_worker() -> None:
    from fastapi import Request

    from app.routes._portable_file_response import portable_request_cancelled

    async def receive():
        return {"type": "http.disconnect"}

    async def exercise() -> bool:
        request = Request({"type": "http", "method": "GET", "path": "/api/exports/portable"}, receive)
        return await anyio.to_thread.run_sync(portable_request_cancelled, request)

    assert asyncio.run(exercise()) is True
