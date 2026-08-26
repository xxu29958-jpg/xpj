from __future__ import annotations

import os
from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime import windows_credentials as credentials
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.windows_file_security import file_dacl_sddl
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest

_SERVICE_SID = "S-1-5-80-100-200-300-400-500"


def _request(tmp_path: Path) -> InstallRequest:
    return InstallRequest(
        schema=REQUEST_SCHEMA,
        command="resume",
        operation_id="11111111-1111-4111-8111-111111111111",
        request_hash="a" * 64,
        target_release_id="1.2.0",
        app_dir=str(tmp_path / "app-dir"),
        data_root=str(tmp_path / "data"),
        program_data_root=str(tmp_path / "program-data"),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256="b" * 64,
    )


def _write_existing_credentials(request: InstallRequest, *, include_pwfile: bool = False) -> None:
    secrets_root = layout.secrets_dir(request)
    secrets_root.mkdir(parents=True)
    for name in credentials.DURABLE_SECRET_NAMES:
        (secrets_root / name).write_text("s" * 32 + "\n", encoding="utf-8")
    if include_pwfile:
        (secrets_root / "postgres.pwfile").write_text("s" * 32 + "\n", encoding="utf-8")
    runtime_env = Path(request.data_root) / "app" / ".env"
    runtime_env.parent.mkdir(parents=True)
    runtime_env.write_text("DATABASE_URL=secret\n", encoding="utf-8")


def _stub_native_inspection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native, "reject_reparse_components", lambda _path: None)
    monkeypatch.setattr(native, "require_trusted_owner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(native, "service_sid", lambda _runner, _name: _SERVICE_SID)


def test_retry_requires_the_exact_dacl_for_every_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    _write_existing_credentials(request)
    _stub_native_inspection(monkeypatch)
    observed: dict[Path, str | None] = {}

    def record_acl(_runner, path: Path, **kwargs) -> None:
        observed[path] = kwargs.get("expected_dacl_sddl")

    monkeypatch.setattr(native, "require_protected_file_acl", record_acl)

    credentials.verify_existing_credentials(object(), request, allow_missing=False)

    secrets_root = layout.secrets_dir(request)
    for name in credentials.DURABLE_SECRET_NAMES:
        assert observed[secrets_root / name] == file_dacl_sddl(())
    assert observed[Path(request.data_root) / "app" / ".env"] == file_dacl_sddl(
        (_SERVICE_SID,)
    )


def test_stable_credential_postcondition_rejects_a_transient_pwfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    _write_existing_credentials(request, include_pwfile=True)
    _stub_native_inspection(monkeypatch)

    with pytest.raises(LifecycleError, match="transient initdb password input"):
        credentials.verify_existing_credentials(object(), request, allow_missing=False)


@pytest.mark.skipif(os.name != "nt", reason="Windows exact DACL contract")
@pytest.mark.parametrize("extra_ace_target", ["pgpass", ".env"])
def test_retry_rejects_an_extra_credential_ace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_ace_target: str,
) -> None:
    request = _request(tmp_path)
    _write_existing_credentials(request)
    _stub_native_inspection(monkeypatch)
    monkeypatch.setattr(native, "_canonical_dacl_sddl", lambda value: value)

    def observed_dacl(path: Path) -> str:
        expected = (
            file_dacl_sddl((_SERVICE_SID,))
            if path.name == ".env"
            else file_dacl_sddl(())
        )
        if path.name == extra_ace_target:
            return expected + "(A;;FR;;;S-1-5-21-100-200-300-1001)"
        return expected

    monkeypatch.setattr(native, "_object_dacl_sddl", observed_dacl)

    with pytest.raises(LifecycleError, match="exact protected DACL"):
        credentials.verify_existing_credentials(object(), request, allow_missing=False)


def test_acl_retry_discards_pwfile_before_observing_stable_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    pwfile = layout.postgres_pwfile(request)
    pwfile.parent.mkdir(parents=True)
    pwfile.write_text("s" * 32 + "\n", encoding="utf-8")
    events: list[str] = []
    adapter = WindowsSecurityAdapter(object(), object())
    monkeypatch.setattr(adapter, "prepare_operation_store", lambda _request: None)
    monkeypatch.setattr(adapter, "protect_runtime_env", lambda _request: None)
    monkeypatch.setattr(native, "reject_reparse_components", lambda _path: None)
    monkeypatch.setattr(native, "protect_directory", lambda *_args, **_kwargs: None)
    def observe_stable_credentials(*_args, **_kwargs) -> None:
        assert not pwfile.exists()
        events.append("verify")

    monkeypatch.setattr(credentials, "verify_existing_credentials", observe_stable_credentials)
    monkeypatch.setattr(credentials, "ensure_credentials", lambda _request: None)

    adapter.apply(request, "acl")

    assert events == ["verify"]
    assert not pwfile.exists()
