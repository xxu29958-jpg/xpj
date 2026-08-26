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


class _RecordingFileSecurity:
    def __init__(self) -> None:
        self.dacls: dict[Path, str] = {}

    def protect_file(
        self,
        _runner: object,
        path: Path,
        *,
        reader_sids: tuple[str, ...],
        code: str,
    ) -> None:
        del code
        self.dacls[path] = file_dacl_sddl(reader_sids)


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


@pytest.mark.parametrize(
    "crash_target",
    [
        "postgres.password",
        "ticketbox_migrator.password",
        "ticketbox_runtime.password",
        "pgpass",
        ".env",
    ],
)
def test_acl_retry_reconciles_each_credential_replace_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_target: str,
) -> None:
    request = _request(tmp_path)
    security = _RecordingFileSecurity()
    _stub_native_inspection(monkeypatch)
    monkeypatch.setattr(
        WindowsSecurityAdapter,
        "prepare_operation_store",
        lambda _self, _request: None,
    )
    monkeypatch.setattr(native, "protect_directory", lambda *_args, **_kwargs: None)

    def require_recorded_acl(
        _runner: object,
        path: Path,
        **kwargs: object,
    ) -> None:
        expected = kwargs.get("expected_dacl_sddl")
        if security.dacls.get(path) != expected:
            raise LifecycleError(
                "credential_acl_untrusted",
                f"credential lacks its exact protected DACL: {path.name}",
            )

    monkeypatch.setattr(native, "require_protected_file_acl", require_recorded_acl)
    original_write = credentials.durable_write_text

    def crash_after_replace(path: Path, text: str) -> None:
        original_write(path, text)
        if path.name == crash_target:
            raise SystemExit("injected hard crash after durable replace")

    monkeypatch.setattr(credentials, "durable_write_text", crash_after_replace)
    with pytest.raises(SystemExit, match="injected hard crash"):
        WindowsSecurityAdapter(object(), security).apply(request, "acl")

    stable_paths = {
        layout.secrets_dir(request) / name for name in credentials.DURABLE_SECRET_NAMES
    } | {Path(request.data_root) / "app" / ".env"}
    preserved = {path: path.read_bytes() for path in stable_paths if path.is_file()}
    assert any(path.name == crash_target for path in preserved)

    pwfile = layout.postgres_pwfile(request)
    pwfile.write_text("p" * 32 + "\n", encoding="utf-8")
    monkeypatch.setattr(credentials, "durable_write_text", original_write)

    WindowsSecurityAdapter(object(), security).apply(request, "acl")

    for path, content in preserved.items():
        assert path.read_bytes() == content
    assert not pwfile.exists()
    for name in credentials.DURABLE_SECRET_NAMES:
        assert security.dacls[layout.secrets_dir(request) / name] == file_dacl_sddl(())
    assert security.dacls[Path(request.data_root) / "app" / ".env"] == file_dacl_sddl(
        (_SERVICE_SID,)
    )
