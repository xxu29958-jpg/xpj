"""Stable UI status contract and user-visible control failures."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from backend_manager.app_controller import AppController, ManagerShuttingDownError
from backend_manager.config import ConfigError, InstalledRuntimeConfig, ManagerConfig, SourceRuntimeConfig
from backend_manager.diagnostic_bundle import DiagnosticBundle
from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.product_data import ProductDataError
from backend_manager.product_identity import ProductCredentialError, ProductSession
from backend_manager.projection import (
    RefreshingInstalledRuntimeConfigProvider,
    UnavailableInstalledRuntimeConfigProvider,
)
from backend_manager.runtime import RuntimeControlError, RuntimeStatus


class FakeRuntime:
    def __init__(self) -> None:
        self.fail_start = False

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            mode="source",
            running=True,
            healthy=True,
            pid=123,
            uptime_seconds=45,
            auto_restart=True,
            auto_restart_configurable=True,
            restarts=2,
            backend_service_state=None,
            database_service_state=None,
            log=["ready"],
            health_state="healthy",
            health_detail="identity verified",
            mobile_endpoint_state="public_configured_unverified",
            android_binding_state="configured_unverified",
            iphone_upload_state="configured_unverified",
            runtime_access_state="available",
            owner_state="configured",
            owner_recovery_channel="managed_host",
        )

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeControlError("需要管理员权限")

    def stop(self) -> None:
        pass

    def restart(self) -> None:
        pass

    def toggle_auto_restart(self) -> bool:
        return True

    def run_monitor(self, _stop_event) -> None:
        pass


def _config() -> ManagerConfig:
    return ManagerConfig(
        runtime=SourceRuntimeConfig(Path("backend"), Path("python.exe"), Path("backend")),
        backend_host="127.0.0.1",
        backend_port=8000,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
        expected_backend_version=None,
        expected_installation_id="ticketbox-0123456789abcdef0123456789abcdef",
        health_request_timeout_seconds=3.0,
    )


def _product_session() -> ProductSession:
    return ProductSession(
        session_token="tbx-desktop-secret",
        account_name="我",
        ledger_id="owner",
        ledger_name="我的小票夹",
        device_name="小票夹 Desktop",
        role="owner",
        expires_at="2026-10-16T00:00:00Z",
    )


def _rebind_recovery_id() -> str:
    return f"{_config().expected_installation_id}:desktop-rebind-recovery-v1"


def _primary_session_loader(session: ProductSession | None):
    return lambda credential_id: session if credential_id == _config().expected_installation_id else None


def _activate_pending(
    _origin: str,
    pending: ProductSession,
    _previous: str | None,
    **_kwargs,
) -> ProductSession:
    return pending


def test_status_exposes_runtime_capabilities(monkeypatch) -> None:
    monkeypatch.setattr("backend_manager.app_controller.lan_ip", lambda: "192.168.1.8")
    controller = AppController(FakeRuntime(), _config())

    status = controller.status()

    assert status["runtime_mode"] == "source"
    assert status["auto_restart_configurable"] is True
    assert status["lan"] == "仅本机监听"
    assert status["control_error"] is None
    assert status["health_state"] == "healthy"
    assert status["health_detail"] == "identity verified"
    assert status["mobile_endpoint_state"] == "public_configured_unverified"
    assert status["android_binding_state"] == "configured_unverified"
    assert status["runtime_access_state"] == "available"


def test_product_workspace_adds_stored_app_principal_only_inside_gateway() -> None:
    calls: list[tuple[str, str, str | None, str, float]] = []

    def fetcher(
        origin: str,
        workspace: str,
        ledger_id: str | None,
        session_token: str,
        *,
        timeout_seconds: float,
    ) -> dict:
        calls.append((origin, workspace, ledger_id, session_token, timeout_seconds))
        return {"workspace": workspace, "rows": [], "ledgers": []}

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_data_fetcher=fetcher,
        product_ledger_fetcher=lambda *_args, **_kwargs: [
            {
                "ledger_id": "owner",
                "name": "我的小票夹",
                "role": "owner",
                "is_default": True,
            },
            {
                "ledger_id": "family",
                "name": "家庭账本",
                "role": "viewer",
                "is_default": False,
            },
        ],
        product_session_loader=lambda _installation_id: _product_session(),
    )

    payload = controller.product_workspace("inbox", "owner")

    assert payload["workspace"] == "inbox"
    assert payload["rows"] == []
    assert payload["ledgers"] == [
        {
            "ledger_id": "owner",
            "name": "我的小票夹",
            "role": "owner",
            "is_default": True,
            "is_current": True,
        },
        {
            "ledger_id": "family",
            "name": "家庭账本",
            "role": "viewer",
            "is_default": False,
            "is_current": False,
        },
    ]
    assert calls == [
        (
            "http://127.0.0.1:8000",
            "inbox",
            "owner",
            "tbx-desktop-secret",
            3.0,
        )
    ]


def test_product_inbox_command_forwards_exact_backend_owned_intent() -> None:
    calls: list[tuple[str, str, str | None, dict, str, str, float]] = []

    def executor(
        origin: str,
        public_id: str,
        ledger_id: str | None,
        payload: dict,
        idempotency_key: str,
        session_token: str,
        *,
        timeout_seconds: float,
    ) -> dict:
        calls.append(
            (
                origin,
                public_id,
                ledger_id,
                payload,
                idempotency_key,
                session_token,
                timeout_seconds,
            )
        )
        return {
            "action": payload["action"],
            "message": "已保存",
            "expense_status": "pending",
            "row_version": 2,
        }

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_command_executor=executor,
        product_session_loader=lambda _installation_id: _product_session(),
    )
    payload = controller.product_inbox_command(
        "expense-public-id",
        "owner",
        {
            "action": "save",
            "expected_row_version": 1,
            "merchant": "修正商家",
        },
        "desktop-save-1",
    )

    assert payload["row_version"] == 2
    assert calls == [
        (
            "http://127.0.0.1:8000",
            "expense-public-id",
            "owner",
            {
                "action": "save",
                "expected_row_version": 1,
                "merchant": "修正商家",
            },
            "desktop-save-1",
            "tbx-desktop-secret",
            3.0,
        )
    ]


def test_cross_account_rebind_stages_recovery_then_activates_before_primary_promotion() -> None:
    current = _product_session()
    replacement = ProductSession(
        session_token="tbx-other-account-token",
        account_name="另一账户",
        ledger_id="other-family",
        ledger_name="另一账户家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        expires_at=None,
    )
    events: list[tuple[str, str]] = []
    stored: list[tuple[str, ProductSession]] = []

    def activate(
        _origin: str,
        pending: ProductSession,
        previous: str | None,
        **_kwargs,
    ) -> ProductSession:
        assert previous == current.session_token
        events.append(("activate", pending.session_token))
        return pending

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=_primary_session_loader(current),
        product_session_pairer=lambda *_args, **_kwargs: (
            events.append(("pair", replacement.session_token)),
            replacement,
        )[-1],
        product_session_activator=activate,
        product_session_deleter=lambda credential_id: events.append(("delete-recovery", credential_id)),
        product_session_saver=lambda credential_id, session: (
            events.append(
                (
                    "save" if credential_id == _config().expected_installation_id else "save-recovery",
                    session.session_token,
                )
            ),
            stored.append((credential_id, session)) if credential_id == _config().expected_installation_id else None,
        ),
    )

    before = controller.product_principal()
    paired = controller.pair_product_principal("12345678")

    assert before["configured"] is True
    assert before["ledger_id"] == current.ledger_id
    assert "session_token" not in before
    assert paired["configured"] is True
    assert "session_token" not in paired
    assert stored == [(_config().expected_installation_id, replacement)]
    assert events == [
        ("pair", replacement.session_token),
        ("save-recovery", replacement.session_token),
        ("activate", replacement.session_token),
        ("save-recovery", replacement.session_token),
        ("save", replacement.session_token),
        ("delete-recovery", _rebind_recovery_id()),
    ]


def test_rebind_recovery_store_failure_never_activates_pending_b() -> None:
    current = _product_session()
    pending = ProductSession(
        session_token="tbx-pending-without-recovery",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        expires_at="2026-07-18T08:05:00Z",
    )
    activations: list[str] = []
    revocations: list[str] = []

    def fail_recovery_save(_credential_id: str, _session: ProductSession) -> None:
        raise ProductCredentialError("synthetic recovery store failure")

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=_primary_session_loader(current),
        product_session_pairer=lambda *_args, **_kwargs: pending,
        product_session_activator=lambda _origin, value, _previous, **_kwargs: (
            activations.append(value.session_token),
            value,
        )[-1],
        product_session_revoker=lambda _origin, token, **_kwargs: revocations.append(token),
        product_session_saver=fail_recovery_save,
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")

    assert error.value.error == "product_credential_unavailable"
    assert activations == []
    assert revocations == []


@pytest.mark.parametrize("operation", ["pair", "switch"])
def test_rebind_same_token_fails_before_recovery_or_activation(
    operation: str,
) -> None:
    current = _product_session()
    writes: list[str] = []
    activations: list[str] = []
    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=_primary_session_loader(current),
        product_session_pairer=lambda *_args, **_kwargs: current,
        product_ledger_switcher=lambda *_args, **_kwargs: current,
        product_session_activator=lambda _origin, value, _previous, **_kwargs: (
            activations.append(value.session_token),
            value,
        )[-1],
        product_session_saver=lambda credential_id, _session: writes.append(credential_id),
    )

    with pytest.raises(ProductDataError) as error:
        if operation == "pair":
            controller.pair_product_principal("12345678")
        else:
            controller.switch_product_principal_ledger("family")

    assert error.value.status_code == 502
    assert error.value.error == "product_identity_rotation_required"
    assert writes == []
    assert activations == []


def test_activation_response_loss_replays_recovery_b_and_promotes_it() -> None:
    current = _product_session()
    pending = ProductSession(
        session_token="tbx-committed-response-lost",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        expires_at="2026-07-18T08:05:00Z",
    )
    credentials = {_config().expected_installation_id: current}
    calls: list[tuple[str, str | None]] = []

    def activate(
        _origin: str,
        value: ProductSession,
        previous: str | None,
        **_kwargs,
    ) -> ProductSession:
        calls.append((value.session_token, previous))
        if len(calls) == 1:
            raise ProductDataError(
                "synthetic committed response loss",
                status_code=503,
            )
        return value

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=credentials.get,
        product_session_pairer=lambda *_args, **_kwargs: pending,
        product_session_activator=activate,
        product_session_saver=credentials.__setitem__,
        product_session_deleter=lambda credential_id: credentials.pop(
            credential_id,
            None,
        ),
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")
    assert error.value.error == "product_rebind_recovery_pending"
    assert credentials[_rebind_recovery_id()] == pending

    projection = controller.product_principal()

    assert projection["ledger_id"] == "family"
    assert credentials == {_config().expected_installation_id: pending}
    assert calls == [
        (pending.session_token, current.session_token),
        (pending.session_token, current.session_token),
    ]


def test_primary_store_failure_leaves_activated_b_in_recovery_slot() -> None:
    current = _product_session()
    replacement = ProductSession(
        session_token="tbx-other-ledger-token",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="owner",
        expires_at=None,
    )
    events: list[tuple[str, str]] = []

    def fail_save(credential_id: str, _session: ProductSession) -> None:
        if credential_id == _rebind_recovery_id():
            events.append(("save-recovery", replacement.session_token))
            return
        events.append(("save-failed", replacement.session_token))
        raise ProductCredentialError("synthetic credential failure")

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=_primary_session_loader(current),
        product_session_pairer=lambda *_args, **_kwargs: replacement,
        product_session_activator=_activate_pending,
        product_session_revoker=lambda _origin, token, **_kwargs: events.append(("revoke", token)),
        product_session_deleter=lambda credential_id: events.append(
            (
                "delete" if credential_id == _config().expected_installation_id else "delete-recovery",
                credential_id,
            )
        ),
        product_session_saver=fail_save,
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")

    assert error.value.status_code == 503
    assert error.value.error == "product_rebind_recovery_pending"
    assert events == [
        ("save-recovery", replacement.session_token),
        ("save-recovery", replacement.session_token),
        ("save-failed", replacement.session_token),
    ]


def test_activation_failure_keeps_b_in_recovery_without_cleanup() -> None:
    current = _product_session()
    replacement = ProductSession(
        session_token="tbx-other-account-token",
        account_name="另一账户",
        ledger_id="other-family",
        ledger_name="另一账户家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        expires_at=None,
    )
    saved: list[ProductSession] = []
    deleted: list[str] = []

    def activation_failure(*_args, **_kwargs) -> ProductSession:
        raise ProductDataError("synthetic activation response loss", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=_primary_session_loader(current),
        product_session_pairer=lambda *_args, **_kwargs: replacement,
        product_session_activator=activation_failure,
        product_session_saver=lambda _credential_id, session: saved.append(session),
        product_session_deleter=deleted.append,
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")

    assert error.value.status_code == 503
    assert error.value.error == "product_rebind_recovery_pending"
    assert saved == [replacement]
    assert deleted == []


def test_recovery_cleanup_failure_after_primary_promotion_is_non_blocking() -> None:
    current = _product_session()
    replacement = ProductSession(
        session_token="tbx-family-token",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        expires_at=None,
    )
    saved: list[ProductSession] = []

    def fail_delete(credential_id: str) -> None:
        if credential_id == _rebind_recovery_id():
            raise ProductCredentialError("synthetic recovery delete failure")

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=_primary_session_loader(current),
        product_session_pairer=lambda *_args, **_kwargs: replacement,
        product_session_activator=_activate_pending,
        product_session_saver=lambda _installation_id, session: saved.append(session),
        product_session_deleter=fail_delete,
    )

    projection = controller.pair_product_principal("12345678")

    assert projection["ledger_id"] == "family"
    assert saved == [replacement, replacement, replacement]


def test_activation_failure_keeps_b_in_recovery_and_primary_a_unchanged() -> None:
    current = _product_session()
    replacement = ProductSession(
        session_token="tbx-recovery-after-old-revoke-failure",
        account_name="另一账户",
        ledger_id="other-family",
        ledger_name="另一账户家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        expires_at=None,
    )
    credentials = {_config().expected_installation_id: current}

    def activation_failure(*_args, **_kwargs) -> ProductSession:
        raise ProductDataError("synthetic activation failure", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=credentials.get,
        product_session_pairer=lambda *_args, **_kwargs: replacement,
        product_session_activator=activation_failure,
        product_session_saver=credentials.__setitem__,
        product_session_deleter=credentials.pop,
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")

    assert error.value.status_code == 503
    assert error.value.error == "product_rebind_recovery_pending"
    assert credentials[_config().expected_installation_id] == current
    assert credentials[_rebind_recovery_id()] == replacement
    assert replacement.session_token not in str(error.value)


def test_expired_recovery_cleanup_failure_does_not_block_active_a() -> None:
    current = _product_session()
    expired = ProductSession(
        session_token="tbx-expired-recovery",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        expires_at="2026-07-18T08:05:00Z",
    )
    credentials = {
        _config().expected_installation_id: current,
        _rebind_recovery_id(): expired,
    }
    activation_attempts = 0
    cleanup_attempts = 0

    def reject_expired(*_args, **_kwargs) -> ProductSession:
        nonlocal activation_attempts
        activation_attempts += 1
        raise ProductDataError(
            "synthetic expired activation",
            error="invalid_token",
            status_code=401,
        )

    def fail_recovery_cleanup(credential_id: str) -> None:
        nonlocal cleanup_attempts
        assert credential_id == _rebind_recovery_id()
        cleanup_attempts += 1
        raise ProductCredentialError("synthetic recovery delete failure")

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=credentials.get,
        product_session_activator=reject_expired,
        product_session_deleter=fail_recovery_cleanup,
    )

    assert controller.product_principal()["ledger_id"] == current.ledger_id
    assert controller.product_principal()["ledger_id"] == current.ledger_id
    assert activation_attempts == 2
    assert cleanup_attempts == 2
    assert credentials[_config().expected_installation_id] == current


def test_recovery_cleanup_failure_is_retried_when_primary_already_b() -> None:
    current = _product_session()
    replacement = ProductSession(
        session_token="tbx-recovery-after-delete-failure",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        expires_at=None,
    )
    credentials = {_config().expected_installation_id: current}

    delete_attempts = 0

    def delete(credential_id: str) -> None:
        nonlocal delete_attempts
        if credential_id == _rebind_recovery_id():
            delete_attempts += 1
            if delete_attempts == 1:
                raise ProductCredentialError("synthetic recovery delete failure")
        credentials.pop(credential_id, None)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=credentials.get,
        product_session_pairer=lambda *_args, **_kwargs: replacement,
        product_session_activator=_activate_pending,
        product_session_saver=credentials.__setitem__,
        product_session_deleter=delete,
    )

    projection = controller.pair_product_principal("12345678")

    assert projection["ledger_id"] == "family"
    assert credentials[_config().expected_installation_id] == replacement
    assert credentials[_rebind_recovery_id()] == replacement
    assert controller.product_principal()["ledger_id"] == "family"
    assert credentials == {_config().expected_installation_id: replacement}


def test_primary_store_failure_keeps_b_in_recovery_slot() -> None:
    current = _product_session()
    replacement = ProductSession(
        session_token="tbx-recovery-after-save-failure",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="owner",
        expires_at=None,
    )
    credentials = {_config().expected_installation_id: current}

    def save(credential_id: str, session: ProductSession) -> None:
        if credential_id == _config().expected_installation_id:
            raise ProductCredentialError("synthetic primary save failure")
        credentials[credential_id] = session

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=credentials.get,
        product_session_pairer=lambda *_args, **_kwargs: replacement,
        product_session_activator=_activate_pending,
        product_session_saver=save,
        product_session_deleter=lambda credential_id: credentials.pop(credential_id, None),
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")

    assert error.value.status_code == 503
    assert error.value.error == "product_rebind_recovery_pending"
    assert credentials[_config().expected_installation_id] == current
    assert credentials[_rebind_recovery_id()] == replacement


def test_rebind_retry_reconciles_recovery_before_issuing_another_token() -> None:
    current = _product_session()
    pending = ProductSession(
        session_token="tbx-pending-recovery-token",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        expires_at=None,
    )
    replacement = ProductSession(
        session_token="tbx-retry-replacement-token",
        account_name="我",
        ledger_id="owner",
        ledger_name="我的小票夹",
        device_name="小票夹 Desktop",
        role="owner",
        expires_at=None,
    )
    credentials = {
        _config().expected_installation_id: current,
        _rebind_recovery_id(): pending,
    }
    events: list[tuple[str, str]] = []

    def pair(*_args, **_kwargs) -> ProductSession:
        events.append(("pair", replacement.session_token))
        return replacement

    def save(credential_id: str, session: ProductSession) -> None:
        events.append(("save", credential_id))
        credentials[credential_id] = session

    def delete(credential_id: str) -> None:
        events.append(("delete", credential_id))
        credentials.pop(credential_id, None)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=credentials.get,
        product_session_pairer=pair,
        product_session_activator=_activate_pending,
        product_session_saver=save,
        product_session_deleter=delete,
    )

    projection = controller.pair_product_principal("12345678")

    assert projection["ledger_id"] == replacement.ledger_id
    assert credentials == {_config().expected_installation_id: replacement}
    assert events[:4] == [
        ("save", _rebind_recovery_id()),
        ("save", _config().expected_installation_id),
        ("delete", _rebind_recovery_id()),
        ("pair", replacement.session_token),
    ]


def test_product_ledger_switch_rotates_and_persists_replacement_session() -> None:
    saved: list[ProductSession] = []
    recovery_events: list[tuple[str, str]] = []
    replacement = ProductSession(
        session_token="tbx-family-token",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        expires_at="2026-10-16T00:00:00Z",
    )
    switch_calls: list[tuple[str, str, str]] = []

    def switcher(origin: str, ledger_id: str, token: str, **_kwargs) -> ProductSession:
        switch_calls.append((origin, ledger_id, token))
        return replacement

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=_primary_session_loader(_product_session()),
        product_ledger_switcher=switcher,
        product_session_activator=_activate_pending,
        product_session_saver=lambda credential_id, session: (
            saved.append(session)
            if credential_id == _config().expected_installation_id
            else recovery_events.append(("save", credential_id))
        ),
        product_session_deleter=lambda credential_id: recovery_events.append(("delete", credential_id)),
    )

    projection = controller.switch_product_principal_ledger("family")

    assert projection["ledger_id"] == "family"
    assert projection["role"] == "viewer"
    assert "session_token" not in projection
    assert switch_calls == [("http://127.0.0.1:8000", "family", "tbx-desktop-secret")]
    assert saved == [replacement]
    assert recovery_events == [
        ("save", _rebind_recovery_id()),
        ("save", _rebind_recovery_id()),
        ("delete", _rebind_recovery_id()),
    ]


def test_ledger_switch_primary_store_failure_keeps_b_recoverable() -> None:
    replacement = ProductSession(
        session_token="tbx-family-token",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        expires_at=None,
    )
    deleted: list[str] = []

    def fail_save(credential_id: str, _session: ProductSession) -> None:
        if credential_id == _rebind_recovery_id():
            return
        raise ProductCredentialError("synthetic credential failure")

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=_primary_session_loader(_product_session()),
        product_ledger_switcher=lambda *_args, **_kwargs: replacement,
        product_session_activator=_activate_pending,
        product_session_saver=fail_save,
        product_session_deleter=deleted.append,
    )

    with pytest.raises(ProductDataError) as error:
        controller.switch_product_principal_ledger("family")

    assert error.value.status_code == 503
    assert error.value.error == "product_rebind_recovery_pending"
    assert deleted == []


def test_ledger_switch_primary_store_failure_keeps_b_in_recovery_slot() -> None:
    current = _product_session()
    replacement = ProductSession(
        session_token="tbx-switch-recovery-token",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        expires_at=None,
    )
    credentials = {_config().expected_installation_id: current}

    def save(credential_id: str, session: ProductSession) -> None:
        if credential_id == _config().expected_installation_id:
            raise ProductCredentialError("synthetic primary save failure")
        credentials[credential_id] = session

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=credentials.get,
        product_ledger_switcher=lambda *_args, **_kwargs: replacement,
        product_session_activator=_activate_pending,
        product_session_saver=save,
        product_session_deleter=lambda credential_id: credentials.pop(credential_id, None),
    )

    with pytest.raises(ProductDataError) as error:
        controller.switch_product_principal_ledger("family")

    assert error.value.status_code == 503
    assert error.value.error == "product_rebind_recovery_pending"
    assert credentials[_config().expected_installation_id] == current
    assert credentials[_rebind_recovery_id()] == replacement


def test_product_workspace_and_token_rotation_are_serialized() -> None:
    fetch_started = threading.Event()
    release_fetch = threading.Event()
    switch_called = threading.Event()
    errors: list[BaseException] = []
    replacement = ProductSession(
        session_token="tbx-family-token",
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        expires_at=None,
    )

    def fetcher(*_args, **_kwargs) -> dict:
        fetch_started.set()
        assert release_fetch.wait(timeout=2)
        return {"workspace": "plans", "rows": [], "ledgers": []}

    def switcher(*_args, **_kwargs) -> ProductSession:
        switch_called.set()
        return replacement

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_data_fetcher=fetcher,
        product_ledger_fetcher=lambda *_args, **_kwargs: [
            {
                "ledger_id": "owner",
                "name": "我的小票夹",
                "role": "owner",
                "is_default": True,
            }
        ],
        product_session_loader=_primary_session_loader(_product_session()),
        product_ledger_switcher=switcher,
        product_session_activator=_activate_pending,
        product_session_saver=lambda *_args: None,
        product_session_deleter=lambda *_args: None,
    )

    def run_workspace() -> None:
        try:
            controller.product_workspace("plans")
        except Exception as exc:  # pragma: no cover - asserted after join
            errors.append(exc)

    def run_switch() -> None:
        try:
            controller.switch_product_principal_ledger("family")
        except Exception as exc:  # pragma: no cover - asserted after join
            errors.append(exc)

    workspace_thread = threading.Thread(target=run_workspace)
    switch_thread = threading.Thread(target=run_switch)
    workspace_thread.start()
    assert fetch_started.wait(timeout=2)
    switch_thread.start()
    assert switch_called.wait(timeout=0.1) is False
    release_fetch.set()
    workspace_thread.join(timeout=2)
    switch_thread.join(timeout=2)

    assert errors == []
    assert switch_called.is_set()


def test_backend_401_clears_the_installation_credential() -> None:
    deleted: list[str] = []

    def denied(*_args, **_kwargs):
        raise ProductDataError(
            "桌面身份已失效",
            error="invalid_token",
            status_code=401,
        )

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_data_fetcher=denied,
        product_session_loader=_primary_session_loader(_product_session()),
        product_session_deleter=deleted.append,
    )

    with pytest.raises(ProductDataError) as error:
        controller.product_workspace("inbox")

    assert error.value.status_code == 401
    assert deleted == [_config().expected_installation_id]


def test_product_workspace_fails_closed_until_pairing() -> None:
    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_loader=lambda _installation_id: None,
    )

    with pytest.raises(ProductDataError) as error:
        controller.product_workspace("inbox")

    assert error.value.status_code == 401
    assert error.value.error == "product_principal_required"


def test_control_failure_is_returned_then_cleared_after_success() -> None:
    runtime = FakeRuntime()
    controller = AppController(runtime, _config())
    runtime.fail_start = True

    controller.start()
    assert controller.status()["control_error"] == "需要管理员权限"

    runtime.fail_start = False
    controller.start()
    assert controller.status()["control_error"] is None
    assert controller.status()["action_notice"] == "启动操作已完成。"

    runtime.fail_start = True
    controller.start()
    failed = controller.status()
    assert failed["control_error"] == "需要管理员权限"
    assert failed["action_notice"] is None


def test_success_notice_expires_without_clearing_persistent_task_result() -> None:
    now = [100.0]
    controller = AppController(FakeRuntime(), _config(), monotonic=lambda: now[0])

    controller.start()
    assert controller.status()["action_notice"] == "启动操作已完成。"

    now[0] += 9.0
    status = controller.status()
    assert status["action_notice"] is None


def test_task_links_open_exact_owner_authority_pages(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", opened.append)
    controller = AppController(FakeRuntime(), _config())

    controller.open_pairing()
    controller.open_devices()
    controller.open_upload_links()
    controller.open_backups()
    controller.open_diagnostics()
    controller.open_settings()

    assert opened == [
        "http://127.0.0.1:8000/owner/pairing",
        "http://127.0.0.1:8000/owner/devices",
        "http://127.0.0.1:8000/owner/upload-links",
        "http://127.0.0.1:8000/owner/backups",
        "http://127.0.0.1:8000/owner/diagnostics",
        "http://127.0.0.1:8000/owner/settings",
    ]
    assert controller.status()["action_notice"] == "任务页面已在浏览器中打开。"


def test_task_link_browser_failure_is_actionable(monkeypatch) -> None:
    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", lambda _url: False)
    controller = AppController(FakeRuntime(), _config())

    controller.open_pairing()

    assert controller.status()["control_error"] == ("无法打开系统浏览器，请检查 Windows 默认浏览器设置后重试。")


def test_mobile_tasks_fail_closed_when_backend_reports_local_only(monkeypatch) -> None:
    opened: list[str] = []

    class LocalOnlyRuntime(FakeRuntime):
        def status(self) -> RuntimeStatus:
            snapshot = super().status()
            return RuntimeStatus(
                **{
                    **snapshot.__dict__,
                    "mobile_endpoint_state": "local_only",
                    "android_binding_state": "setup_required",
                    "iphone_upload_state": "setup_required",
                },
            )

    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", opened.append)
    controller = AppController(LocalOnlyRuntime(), _config())

    controller.open_pairing()
    assert "尚未配置手机可达入口" in controller.status()["control_error"]
    controller.open_upload_links()
    assert "尚未配置 iPhone 上传入口" in controller.status()["control_error"]
    assert opened == []


def test_task_link_revalidates_backend_identity_before_opening(monkeypatch) -> None:
    opened: list[str] = []

    class MismatchedRuntime(FakeRuntime):
        def status(self) -> RuntimeStatus:
            snapshot = super().status()
            return RuntimeStatus(
                **{
                    **snapshot.__dict__,
                    "healthy": False,
                    "health_state": "mismatch",
                    "health_detail": "foreign listener",
                },
            )

    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", opened.append)
    controller = AppController(MismatchedRuntime(), _config())

    controller.open_pairing()

    assert opened == []
    assert "身份尚未验证" in controller.status()["control_error"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("runtime_access_state", "repair_required", "安装维护尚未完成"),
        ("owner_state", "recovery_required", "不能自动重建身份"),
    ],
)
def test_owner_tasks_fail_closed_for_distinct_recovery_states(
    monkeypatch,
    field: str,
    value: str,
    message: str,
) -> None:
    opened: list[str] = []

    class RecoveryRuntime(FakeRuntime):
        def status(self) -> RuntimeStatus:
            snapshot = super().status()
            return RuntimeStatus(**{**snapshot.__dict__, field: value})

    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", opened.append)
    controller = AppController(RecoveryRuntime(), _config())

    controller.open_console()

    assert opened == []
    assert message in controller.status()["control_error"]


def test_diagnostic_export_exposes_only_file_name_and_human_notice(monkeypatch, tmp_path) -> None:
    bundle = DiagnosticBundle(tmp_path / "Ticketbox-Diagnostics-20260713-000000Z.zip")
    monkeypatch.setattr("backend_manager.app_controller.export_diagnostic_bundle", lambda _status: bundle)
    controller = AppController(FakeRuntime(), _config())

    controller.export_diagnostics()
    status = controller.status()

    assert status["diagnostic_bundle_file"] == bundle.file_name
    assert status["action_notice"] == "诊断包已保存到当前用户的下载文件夹。"
    assert str(tmp_path) not in str(status)


def _installed_config(tmp_path: Path, *, port: int, service_suffix: str) -> ManagerConfig:
    layout = InstalledLayout(
        install_dir=tmp_path / f"program-{service_suffix}",
        data_root=tmp_path / f"data-{service_suffix}",
        backend_port=port,
        pg_port=5432,
        backend_service_name=f"TicketboxBackend{service_suffix}",
        pg_service_name=f"TicketboxPg{service_suffix}",
        backend_version=f"1.0.{port}",
    )
    release = WindowsReleaseConfig(
        backend_service_name=layout.backend_service_name,
        pg_service_name=layout.pg_service_name,
        service_state_timeout_ms=10_000,
        service_poll_interval_ms=100,
        postgres_ready_timeout_ms=20_000,
        backend_ready_timeout_ms=30_000,
        backend_ready_poll_interval_ms=200,
        backend_health_request_timeout_ms=1_000,
    )
    return ManagerConfig(
        runtime=InstalledRuntimeConfig(layout, release),
        backend_host="127.0.0.1",
        backend_port=port,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
        expected_backend_version=layout.backend_version,
        expected_installation_id=layout.installation_id,
        health_request_timeout_seconds=1.0,
    )


def test_installed_controller_refreshes_projection_for_status_action_and_console(monkeypatch, tmp_path: Path) -> None:
    configs = [
        _installed_config(tmp_path, port=8101, service_suffix="Old"),
        _installed_config(tmp_path, port=8202, service_suffix="New"),
        _installed_config(tmp_path, port=8404, service_suffix="Action"),
        _installed_config(tmp_path, port=8303, service_suffix="Console"),
    ]
    actions: list[tuple[str, int]] = []

    class Runtime(FakeRuntime):
        def __init__(self, config: ManagerConfig) -> None:
            super().__init__()
            self._config = config

        def status(self) -> RuntimeStatus:
            snapshot = super().status()
            return RuntimeStatus(**{**snapshot.__dict__, "mode": "installed"})

        def start(self) -> None:
            actions.append((self._config.runtime.backend_service_name, self._config.backend_port))

    provider = RefreshingInstalledRuntimeConfigProvider(
        config_loader=lambda: configs.pop(0),
        runtime_builder=Runtime,
    )
    opened: list[str] = []
    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", opened.append)
    controller = AppController(provider)

    assert controller.status()["port"] == 8101
    assert controller.status()["public_endpoint_state"] == "public_configured_unverified"
    controller.start()
    controller.open_console()

    assert actions == [("TicketboxBackendAction", 8404)]
    assert opened == ["http://127.0.0.1:8303/owner"]


def test_installed_refresh_failure_does_not_reuse_stale_projection(tmp_path: Path) -> None:
    calls = 0
    config = _installed_config(tmp_path, port=8101, service_suffix="Old")

    def load() -> ManagerConfig:
        nonlocal calls
        calls += 1
        if calls == 1:
            return config
        raise ConfigError(r"secret path C:\ProgramData\Ticketbox\app\.env")

    provider = RefreshingInstalledRuntimeConfigProvider(
        config_loader=load, runtime_builder=lambda _config: FakeRuntime()
    )
    controller = AppController(provider)

    assert controller.status()["port"] == 8101
    unavailable = controller.status()
    controller.start()

    assert unavailable["port"] is None
    assert unavailable["owner_url"] is None
    assert "ProgramData" not in unavailable["control_error"]
    assert "安装信息已变化或不可用" in unavailable["control_error"]


def test_installed_monitor_reloads_projection_on_each_tick(tmp_path: Path) -> None:
    stop_event = threading.Event()
    ports: list[int] = []
    configs = iter(
        [
            _installed_config(tmp_path, port=8101, service_suffix="One"),
            _installed_config(tmp_path, port=8202, service_suffix="Two"),
        ],
    )

    class Runtime(FakeRuntime):
        def __init__(self, config: ManagerConfig) -> None:
            super().__init__()
            self._config = config

        def status(self) -> RuntimeStatus:
            ports.append(self._config.backend_port)
            if len(ports) == 2:
                stop_event.set()
            return super().status()

    provider = RefreshingInstalledRuntimeConfigProvider(
        config_loader=lambda: next(configs),
        runtime_builder=Runtime,
        monitor_seconds=0.001,
    )

    provider.run_monitor(stop_event)

    assert ports == [8101, 8202]


def test_shutdown_seal_is_idempotent_and_rejects_direct_actions() -> None:
    shutdown_requests: list[str] = []
    controller = AppController(
        UnavailableInstalledRuntimeConfigProvider(),
        maintenance_version="1.2.0",
        startup_failure_code="release_contract_invalid",
        startup_failure_stage="runtime_discovery",
        request_shutdown=lambda: shutdown_requests.append("shutdown"),
    )

    controller.request_manager_shutdown()
    controller.request_manager_shutdown()

    assert controller.is_manager_shutting_down() is True
    assert shutdown_requests == ["shutdown"]
    assert controller.status()["startup_failure_code"] == "release_contract_invalid"
    assert controller.status()["startup_failure_stage"] == "runtime_discovery"
    for action in (
        controller.start,
        controller.stop,
        controller.restart,
        controller.auto_restart,
        controller.open_console,
        controller.open_pairing,
        controller.open_devices,
        controller.open_upload_links,
        controller.open_backups,
        controller.open_diagnostics,
        controller.open_settings,
        controller.export_diagnostics,
    ):
        with pytest.raises(ManagerShuttingDownError):
            action()


def test_missing_installed_service_disables_scm_actions(tmp_path: Path) -> None:
    config = _installed_config(tmp_path, port=8101, service_suffix="Missing")

    class MissingRuntime(FakeRuntime):
        def status(self) -> RuntimeStatus:
            snapshot = super().status()
            return RuntimeStatus(
                **{
                    **snapshot.__dict__,
                    "mode": "installed",
                    "running": False,
                    "healthy": False,
                    "backend_service_state": "missing",
                    "database_service_state": "running",
                    "health_state": "pending",
                    "health_detail": "backend service missing",
                },
            )

    status = AppController(MissingRuntime(), config).status()

    assert status["backend_service_state"] == "missing"
    assert status["service_controls_available"] is False
    assert "maintenance_available" not in status
