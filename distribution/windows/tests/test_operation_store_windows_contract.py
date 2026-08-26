from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest
from ticketbox_lifecycle.runtime import windows_dacl
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.windows_file_security import WindowsFileSecurity, file_dacl_sddl
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows operation-store ACL contract")


def test_backend_reader_can_inspect_exact_authority_without_browse_or_write(
    tmp_path: Path,
) -> None:
    reader_sid = native.current_process_user_sid()
    assert reader_sid is not None
    service_sid = "S-1-5-80-2773621439-1206139620-3556766058-292034643-3006528458"
    root = tmp_path / "programdata"
    machine = root / "machine"
    operations = machine / "operations"
    operations.mkdir(parents=True)
    active = operations / "active.json"
    active.write_bytes(b"{}\n")
    windows_dacl.apply_protected_dacl(
        active,
        file_dacl_sddl((reader_sid,)),
        code="test_active_acl_failed",
    )
    production_policy = native._lifecycle_directory_sddl(service_sid, None)
    reader_policy = ("D:P" + production_policy[production_policy.rindex("(A;;") :]).replace(
        service_sid,
        reader_sid,
    )
    for path in (operations, machine, root):
        windows_dacl.apply_protected_dacl(
            path,
            reader_policy,
            code="test_operation_store_acl_failed",
        )

    try:
        for path in (root, machine, operations, active):
            path.lstat()
        assert active.read_bytes() == b"{}\n"
        with pytest.raises(PermissionError):
            list(operations.iterdir())
        with pytest.raises(PermissionError):
            (operations / "forbidden.json").write_bytes(b"{}\n")
    finally:
        cleanup_policy = (
            "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
            f"(A;OICI;FA;;;{reader_sid})"
        )
        for path in (root, machine, operations):
            windows_dacl.apply_protected_dacl(
                path,
                cleanup_policy,
                code="test_operation_store_cleanup_failed",
            )


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


def test_active_publication_before_scm_preserves_bounded_directory_policies(tmp_path: Path) -> None:
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
    before = tuple(native._object_dacl_sddl(path) for path in paths)
    active = root / "machine" / "operations" / "active.json.pending.tmp"
    active.write_text("{}\n", encoding="utf-8")

    security.protect_machine_json(active, request.backend_service_name)
    security.verify_machine_json(active, request.backend_service_name)
    security.prepare_operation_store(request)

    assert tuple(native._object_dacl_sddl(path) for path in paths) == before
    backend_sid = native.service_sid(runner, request.backend_service_name)
    interactive_sid = security._installation_reader_sid()
    backend_only = native._canonical_lifecycle_directory_sddl(backend_sid, None)
    manager_ancestor = native._canonical_lifecycle_directory_sddl(
        backend_sid, interactive_sid
    )
    assert before == (manager_ancestor, manager_ancestor, backend_only)


def test_empty_unreadable_programdata_namespace_is_replaced_with_exact_policy(
    tmp_path: Path,
) -> None:
    if not ctypes.windll.shell32.IsUserAnAdmin():
        if os.environ.get("CI"):
            pytest.fail("Windows operation-store contract lane must run elevated")
        pytest.skip("production operation-store contract requires an elevated token")
    request = _request(tmp_path)
    root = Path(request.program_data_root)
    root.mkdir()
    current_sid = native.current_process_user_sid()
    assert current_sid is not None
    windows_dacl.apply_protected_dacl(
        root,
        f"D:P(D;;0x1;;;BA)(A;OICI;FA;;;{current_sid})",
        code="test_untrusted_product_root_failed",
    )
    runner = SubprocessCommandRunner()
    security = WindowsSecurityAdapter(runner, WindowsFileSecurity())

    with pytest.raises(PermissionError):
        list(root.iterdir())
    security.require_fresh_inputs(request)
    security.prepare_operation_store(request)

    backend_sid = native.service_sid(runner, request.backend_service_name)
    expected = native._canonical_lifecycle_directory_sddl(
        backend_sid,
        security._installation_reader_sid(),
    )
    assert native._object_dacl_sddl(root) == expected
