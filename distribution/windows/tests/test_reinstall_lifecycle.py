"""Tests for Rev3.2 §9.7 preserved-data reinstall lifecycle."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from _uninstall_reinstall_fixtures import INSTALL_ID, _installed_fixture
from ticketbox_lifecycle.domain.planner import plan_fresh_install
from ticketbox_lifecycle.domain.reinstall import reinstall
from ticketbox_lifecycle.domain.restore import restore
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation


def test_reinstall_preserves_data_and_identity_without_initdb_while_fresh_and_restore_stay_strict(tmp_path: Path) -> None:
    req, stores, adapters, binding = _installed_fixture(tmp_path)
    stores.pg_service_present = False
    stores.backend_service_present = False
    adapters.postgres._done.update(("start_postgres", "roles_database"))
    adapters.alembic._done.add("alembic")
    events: list[str] = []

    class FakeReinstallPlatform:
        def publish_and_verify_program_acls(self, _req):
            events.append("program_acls")

        def verify_preserved_dataset(self, _req, _binding):
            events.append("verify_preserved_dataset")
            return {"verified_originals": 2}

        def verify_candidate_health(self, _req):
            events.append("candidate_health")

        def verify_normal_health(self, _req):
            events.append("normal_health")

        def update_start_menu_shortcut(self, _req):
            events.append("update_shortcut")

    # Fresh install MUST still refuse existing binding/pgdata.
    with pytest.raises(LifecycleViolation) as fresh_exc:
        plan_fresh_install(replace(req, command="install"), stores.observe(req))
    assert fresh_exc.value.code == "already_installed"

    # R1/R2 restore MUST still refuse non-empty target.
    with pytest.raises(LifecycleError) as restore_exc:
        restore(
            stores.as_lifecycle_stores(),
            replace(req, command="restore"),
            tmp_path / "copy.tbxcold",
            "a" * 64,
            SimpleNamespace(),
        )
    assert restore_exc.value.code == "restore_target_not_empty"

    # Narrow reinstall succeeds without initdb and preserves dataset_id, install_id, restore_epoch.
    reinstall_req = replace(req, command="reinstall", operation_id=f"reinstall-{req.release_manifest_sha256}")
    result = reinstall(stores.as_lifecycle_stores(), reinstall_req, FakeReinstallPlatform())

    assert result.ok is True
    assert result.code == "reinstalled_data_preserved"
    assert result.phase == "committed"
    assert result.client_generation == INSTALL_ID
    assert result.restore_epoch == 1
    assert "postgres_initdb" not in adapters.applied
    assert events == [
        "program_acls",
        "verify_preserved_dataset",
        "candidate_health",
        "update_shortcut",
        "normal_health",
    ]
    assert stores.read().install_id == binding.install_id
    assert stores.read().dataset_id == binding.dataset_id
    assert stores.read().expected_restore_epoch == binding.expected_restore_epoch
    assert adapters.scm.autostart_enabled is True
    assert stores.history[-1].kind == "reinstall"


def test_reinstall_refuses_orphan_pgdata_and_version_mismatch(tmp_path: Path) -> None:
    req, stores, _adapters, binding = _installed_fixture(tmp_path)
    platform = SimpleNamespace()
    reinstall_req = replace(req, command="reinstall", operation_id=f"reinstall-{req.release_manifest_sha256}")

    # Version/manifest mismatch refused.
    stores._binding = replace(binding, active_release_id="1.2.1")
    with pytest.raises(LifecycleViolation) as ver_exc:
        reinstall(stores.as_lifecycle_stores(), reinstall_req, platform)
    assert ver_exc.value.code == "reinstall_version_mismatch"

    # Orphan pgdata without verified installation.json refused.
    stores._binding = None
    with pytest.raises(LifecycleViolation) as orphan_exc:
        reinstall(stores.as_lifecycle_stores(), reinstall_req, platform)
    assert orphan_exc.value.code == "reinstall_binding_missing"
