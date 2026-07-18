"""C08: revalidate Web/Desktop principals at the /web command boundary."""

from __future__ import annotations

import ast
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response as HttpxResponse
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.middleware import web_session as web_session_middleware
from app.middleware.web_session import (
    DESKTOP_BRIDGE_HEADER,
    DESKTOP_BRIDGE_VERSION,
)
from app.models import (
    Account,
    AuthToken,
    DashboardCardPreference,
    Device,
    Ledger,
    LedgerMember,
)
from app.routes import web_common as web_common_routes
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.identity_service import hash_secret, new_session_token
from app.services.session_credential_lock import lock_bootstrap_owner_transaction
from app.services.time_service import now_utc

LOOPBACK_BASE_URL = "http://127.0.0.1:8000"
PUBLIC_BASE_URL = "https://api.example.com"


@dataclass(frozen=True)
class _Principal:
    token: str
    account_id: int
    ledger_id: str


@dataclass(frozen=True)
class _ClientContract:
    base_url: str
    peer: tuple[str, int]
    headers: dict[str, str]


def _principal_headers(token: str) -> dict[str, str]:
    return {
        DESKTOP_BRIDGE_HEADER: DESKTOP_BRIDGE_VERSION,
        "Authorization": f"Bearer {token}",
    }


def _client_contract(platform: str, token: str) -> _ClientContract:
    if platform == "desktop":
        return _ClientContract(
            base_url=LOOPBACK_BASE_URL,
            peer=("127.0.0.1", 51006),
            headers=_principal_headers(token),
        )
    return _ClientContract(
        base_url=PUBLIC_BASE_URL,
        peer=("203.0.113.12", 51007),
        headers={},
    )


def _mint_principal(
    *,
    ledger_id: str = "owner",
    role: str = "member",
    platform: str,
) -> _Principal:
    token = new_session_token()
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id))
        assert ledger is not None
        account = Account(display_name=f"fresh-{platform}-{role}-{uuid4()}")
        db.add(account)
        db.flush()
        db.add(
            LedgerMember(
                ledger_id=ledger_id,
                account_id=account.id,
                role=role,
            )
        )
        device = Device(
            account_id=account.id,
            device_name=f"pytest-{platform}-fresh-principal",
            platform=platform,
        )
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account.id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
                expires_at=now_utc() + timedelta(hours=8),
            )
        )
        db.commit()
        return _Principal(
            token=token,
            account_id=account.id,
            ledger_id=ledger_id,
        )


def _csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None, html
    return match.group(1)


def _seed_dashboard_preference(ledger_id: str) -> None:
    with SessionLocal() as db:
        row = db.scalar(
            select(DashboardCardPreference)
            .where(DashboardCardPreference.tenant_id == ledger_id)
            .where(DashboardCardPreference.surface == "web")
            .where(DashboardCardPreference.card_key == "monthly_spend")
        )
        if row is None:
            row = DashboardCardPreference(
                tenant_id=ledger_id,
                surface="web",
                card_key="monthly_spend",
                position=0,
                visible=False,
            )
            db.add(row)
        else:
            row.position = 0
            row.visible = False
        db.commit()


def _dashboard_preference_survived(ledger_id: str) -> bool:
    with SessionLocal() as db:
        row = db.scalar(
            select(DashboardCardPreference)
            .where(DashboardCardPreference.tenant_id == ledger_id)
            .where(DashboardCardPreference.surface == "web")
            .where(DashboardCardPreference.card_key == "monthly_spend")
        )
        return row is not None and row.visible is False


def _unsafe_route_functions() -> tuple[
    dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    list[tuple[str, str]],
]:
    routes_dir = Path(__file__).resolve().parents[1] / "app" / "routes"
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    unsafe_routes: list[tuple[str, str]] = []
    for path in routes_dir.glob("web_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            qualified_name = f"{path.name}:{node.name}"
            functions[qualified_name] = node
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in {"post", "put", "patch", "delete"}
                ):
                    unsafe_routes.append((path.name, node.name))
    return functions, unsafe_routes


def _local_calls(node: ast.AST) -> set[str]:
    return {call.func.id for call in ast.walk(node) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}


def _reaches_local_call(
    *,
    module_name: str,
    function_name: str,
    target: str,
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    visited: set[str] | None = None,
) -> bool:
    qualified_name = f"{module_name}:{function_name}"
    if qualified_name not in functions:
        return function_name == target
    seen = set() if visited is None else visited
    if qualified_name in seen:
        return False
    seen.add(qualified_name)
    calls = _local_calls(functions[qualified_name])
    if target in calls:
        return True
    return any(
        _reaches_local_call(
            module_name=module_name,
            function_name=called,
            target=target,
            functions=functions,
            visited=seen,
        )
        for called in calls
        if f"{module_name}:{called}" in functions
    )


def test_every_web_business_unsafe_route_reaches_fresh_principal_gate() -> None:
    """Executable C08 inventory: auth lifecycle is the only business exception."""
    functions, unsafe_routes = _unsafe_route_functions()
    auth_exceptions = {
        ("web_auth.py", "web_login_submit"),
        ("web_auth.py", "web_logout"),
    }
    business_routes = [route for route in unsafe_routes if route not in auth_exceptions]

    assert len(unsafe_routes) == 83
    assert len(business_routes) == 81
    missing = [
        route
        for route in business_routes
        if not _reaches_local_call(
            module_name=route[0],
            function_name=route[1],
            target="_resolve_selected_ledger_id",
            functions=functions,
        )
    ]
    assert missing == []

    wrong_order: list[str] = []
    for qualified_name, node in functions.items():
        calls = [
            call
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in {"_resolve_selected_ledger_id", "_require_selected_ledger_write"}
        ]
        resolve_lines = [
            call.lineno
            for call in calls
            if isinstance(call.func, ast.Name) and call.func.id == "_resolve_selected_ledger_id"
        ]
        write_lines = [
            call.lineno
            for call in calls
            if isinstance(call.func, ast.Name) and call.func.id == "_require_selected_ledger_write"
        ]
        if resolve_lines and write_lines and min(resolve_lines) >= min(write_lines):
            wrong_order.append(qualified_name)
    assert wrong_order == []


def _revoke_token_for_command_test(token_value: str) -> None:
    with SessionLocal() as db:
        lock_bootstrap_owner_transaction(db)
        token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value)))
        assert token is not None
        token.revoked_at = now_utc()
        token.grace_until = now_utc() + timedelta(minutes=5)
        db.commit()


@pytest.mark.real_db
@pytest.mark.parametrize("platform", ["desktop", "web"])
def test_unsafe_command_rechecks_revoked_desktop_and_web_principals(
    identity,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    del identity
    principal = _mint_principal(platform=platform)
    _seed_dashboard_preference(principal.ledger_id)
    contract = _client_contract(platform, principal.token)

    if platform == "desktop":
        original = web_session_middleware.authenticate_desktop_session_token

        def authenticate_then_revoke(db, token_value: str):
            auth = original(db, token_value)
            _revoke_token_for_command_test(token_value)
            return auth

        auth_attribute = "authenticate_desktop_session_token"
        auth_wrapper = authenticate_then_revoke
    else:
        original_web = web_session_middleware.authenticate_web_session_token

        def authenticate_web_then_revoke(db, token_value: str, *, ttl_seconds: int):
            result = original_web(db, token_value, ttl_seconds=ttl_seconds)
            _revoke_token_for_command_test(token_value)
            return result

        auth_attribute = "authenticate_web_session_token"
        auth_wrapper = authenticate_web_then_revoke

    with TestClient(
        app,
        base_url=contract.base_url,
        client=contract.peer,
    ) as principal_client:
        if platform == "web":
            principal_client.cookies.set(SESSION_COOKIE_NAME, principal.token, path="/")
        page = principal_client.get(
            "/web/dashboard/cards",
            headers=contract.headers,
        )
        assert page.status_code == 200, page.text
        token = _csrf_token(page.text)
        monkeypatch.setattr(
            web_session_middleware,
            auth_attribute,
            auth_wrapper,
        )
        response = principal_client.post(
            "/web/dashboard/cards/reset",
            data={"ledger_id": principal.ledger_id, "csrf_token": token},
            headers={**contract.headers, "Origin": contract.base_url},
            follow_redirects=False,
        )

    assert response.status_code == 401, response.text
    assert response.json()["error"] == "invalid_token"
    assert _dashboard_preference_survived(principal.ledger_id)


def _install_fresh_guard_probe(
    monkeypatch: pytest.MonkeyPatch,
    fresh_lock_requested: threading.Event,
) -> None:
    original = web_common_routes.lock_and_revalidate_web_session_principal

    def observed_fresh_guard(*args, **kwargs):
        fresh_lock_requested.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(
        web_common_routes,
        "lock_and_revalidate_web_session_principal",
        observed_fresh_guard,
    )


def _install_gated_initial_auth(
    monkeypatch: pytest.MonkeyPatch,
    *,
    platform: str,
    authenticated: threading.Event,
    proceed: threading.Event,
) -> None:
    if platform == "desktop":
        original = web_session_middleware.authenticate_desktop_session_token

        def gated_authentication(db, token_value: str):
            auth = original(db, token_value)
            authenticated.set()
            assert proceed.wait(timeout=5)
            return auth

        attribute = "authenticate_desktop_session_token"
        wrapper = gated_authentication
    else:
        original_web = web_session_middleware.authenticate_web_session_token

        def gated_web_authentication(db, token_value: str, *, ttl_seconds: int):
            result = original_web(db, token_value, ttl_seconds=ttl_seconds)
            authenticated.set()
            assert proceed.wait(timeout=5)
            return result

        attribute = "authenticate_web_session_token"
        wrapper = gated_web_authentication
    monkeypatch.setattr(web_session_middleware, attribute, wrapper)


def _post_while_demotion_holds_lock(
    client: TestClient,
    *,
    principal: _Principal,
    contract: _ClientContract,
    csrf_token: str,
    authenticated: threading.Event,
    proceed: threading.Event,
    fresh_lock_requested: threading.Event,
) -> HttpxResponse:
    with ThreadPoolExecutor(max_workers=1) as pool, SessionLocal() as blocker:
        future = pool.submit(
            client.post,
            "/web/dashboard/cards/reset",
            data={"ledger_id": principal.ledger_id, "csrf_token": csrf_token},
            headers={**contract.headers, "Origin": contract.base_url},
            follow_redirects=False,
        )
        assert authenticated.wait(timeout=2)
        lock_bootstrap_owner_transaction(blocker)
        member = blocker.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == principal.ledger_id)
            .where(LedgerMember.account_id == principal.account_id)
        )
        assert member is not None and member.role == "member"
        member.role = "viewer"
        proceed.set()
        assert fresh_lock_requested.wait(timeout=2)
        time.sleep(0.2)
        assert not future.done()
        blocker.commit()
        return future.result(timeout=5)


def _run_member_demotion_race(
    monkeypatch: pytest.MonkeyPatch,
    *,
    platform: str,
) -> tuple[_Principal, HttpxResponse]:
    principal = _mint_principal(platform=platform)
    _seed_dashboard_preference(principal.ledger_id)
    contract = _client_contract(platform, principal.token)
    authenticated = threading.Event()
    proceed = threading.Event()
    fresh_lock_requested = threading.Event()
    _install_fresh_guard_probe(monkeypatch, fresh_lock_requested)

    with TestClient(
        app,
        base_url=contract.base_url,
        client=contract.peer,
    ) as principal_client:
        if platform == "web":
            principal_client.cookies.set(SESSION_COOKIE_NAME, principal.token, path="/")
        page = principal_client.get(
            "/web/dashboard/cards",
            headers=contract.headers,
        )
        assert page.status_code == 200, page.text
        _install_gated_initial_auth(
            monkeypatch,
            platform=platform,
            authenticated=authenticated,
            proceed=proceed,
        )
        response = _post_while_demotion_holds_lock(
            principal_client,
            principal=principal,
            contract=contract,
            csrf_token=_csrf_token(page.text),
            authenticated=authenticated,
            proceed=proceed,
            fresh_lock_requested=fresh_lock_requested,
        )
    return principal, response


@pytest.mark.real_db
@pytest.mark.parametrize("platform", ["desktop", "web"])
def test_member_demotion_wins_lock_before_command_and_blocks_write(
    identity,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    del identity
    principal, response = _run_member_demotion_race(
        monkeypatch,
        platform=platform,
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"] == "permission_denied"
    assert _dashboard_preference_survived(principal.ledger_id)
