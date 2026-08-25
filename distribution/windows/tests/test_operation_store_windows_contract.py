from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.windows_file_security import WindowsFileSecurity
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows operation-store ACL contract")


def _request(tmp_path: Path) -> InstallRequest:
    return InstallRequest(
        schema=REQUEST_SCHEMA,
        command="install",
        operation_id="11111111-1111-4111-8111-111111111111",
        request_hash="a" * 64,
        target_release_id="1.2.0",
        app_dir=str(tmp_path / "app"),
        data_root=str(tmp_path / "programdata" / "data"),
        program_data_root=str(tmp_path / "programdata"),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxAclContractUnregistered",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256="b" * 64,
        install_id="22222222-2222-4222-8222-222222222222",
        dataset_id="33333333-3333-4333-8333-333333333333",
        schema_revision="20260821_0001",
    )


def test_active_publication_before_scm_preserves_the_single_directory_policy(tmp_path: Path) -> None:
    if not ctypes.windll.shell32.IsUserAnAdmin():
        if os.environ.get("CI"):
            pytest.fail("Windows operation-store contract lane must run elevated")
        pytest.skip("production operation-store contract requires an elevated token")
    request = _request(tmp_path)
    runner = SubprocessCommandRunner()
    assert runner.run(["sc.exe", "query", request.backend_service_name]).returncode != 0
    security = WindowsSecurityAdapter(runner, WindowsFileSecurity())
    security.prepare_operation_store(request)
    root = Path(request.program_data_root)
    paths = (root, root / "machine", root / "machine" / "operations")
    before = tuple(native._directory_security_sddl(path) for path in paths)
    active = root / "machine" / "operations" / "active.json.pending.tmp"
    active.write_text("{}\n", encoding="utf-8")

    security.protect_machine_json(active, request.backend_service_name)
    security.verify_machine_json(active, request.backend_service_name)
    security.prepare_operation_store(request)

    assert tuple(native._directory_security_sddl(path) for path in paths) == before
    assert all("S-1-5-80-" in descriptor for descriptor in before)
    assert all("(A;;WP;" in descriptor for descriptor in before)
