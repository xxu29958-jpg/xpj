"""Connector authority is readable only by the paired loopback Desktop bridge."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import desktop
from tests.desktop_activation_support import LOOPBACK_BASE_URL, _bridge_headers, _desktop_session


@pytest.fixture
def loopback_client(identity):
    del identity
    with TestClient(app, base_url=LOOPBACK_BASE_URL, client=("127.0.0.1", 51011)) as value:
        yield value


def test_connector_projection_uses_live_desktop_auth_and_reports_unsupported_host(client, identity, loopback_client):
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")
    response = loopback_client.get("/desktop/public-connectivity", headers=_bridge_headers(token))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "schema": "ticketbox-connector-projection-v1", "supported": False,
        "binding": None, "public_origin_revision": 0, "state": None,
        "operation": None, "lifecycle_busy": False,
    }
    assert token not in response.text
    assert loopback_client.get("/desktop/public-connectivity").status_code == 401


@pytest.mark.parametrize("case,expected", [
    ("anonymous", 401), ("android", 401), ("missing_bridge", 401),
    ("public_host", 403), ("remote_peer", 403),
])
def test_connector_projection_rejects_wrong_consumer_before_reading_authority(
    client, identity, loopback_client, monkeypatch, case, expected,
):
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")
    bridge = _bridge_headers(token)
    if case == "anonymous":
        bridge.pop("Authorization")
    elif case == "android":
        bridge.update(identity.app_headers)
    elif case == "missing_bridge":
        bridge = headers
    elif case == "public_host":
        bridge["Host"] = "public.example.com"
    monkeypatch.setattr(desktop, "connector_projection", lambda: pytest.fail("unauthorized authority read"))
    if case == "remote_peer":
        with TestClient(app, base_url=LOOPBACK_BASE_URL, client=("203.0.113.7", 51011)) as remote:
            response = remote.get("/desktop/public-connectivity", headers=bridge)
    else:
        response = loopback_client.get("/desktop/public-connectivity", headers=bridge)
    assert response.status_code == expected, response.text


def test_connector_projection_read_failure_has_one_safe_error(client, identity, loopback_client, monkeypatch, caplog):
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")
    secret = "private-connector-record-must-not-reach-the-response"

    def fail():
        raise OSError(secret)

    monkeypatch.setattr(desktop, "connector_projection", fail)
    response = loopback_client.get("/desktop/public-connectivity", headers=_bridge_headers(token))
    assert response.status_code == 503
    assert response.json()["error"] == "connector_projection_unavailable"
    assert "刷新" in response.json()["message"]
    assert secret not in response.text + caplog.text and token not in response.text + caplog.text


def test_connector_projection_handles_cross_release_committed_removal_and_rejects_unlinked_history(
    tmp_path,
    monkeypatch,
):
    import hashlib
    import json
    from types import SimpleNamespace

    from app.services import windows_connector_projection as proj_mod
    from app.windows_connector_authority import ConnectorAuthorityError

    install_id = "11111111-1111-4111-8111-111111111111"
    dataset_id = "22222222-2222-4222-8222-222222222222"
    remove_op_id = "33333333-3333-4333-8333-333333333333"
    sha_a = "a" * 64
    sha_b = "b" * 64

    root = tmp_path / "Ticketbox"
    data_app = root / "data" / "app"
    machine = root / "machine"
    history = machine / "operations" / "history"
    conn_dir = machine / "connectors" / "cloudflare"
    data_app.mkdir(parents=True)
    history.mkdir(parents=True)
    conn_dir.mkdir(parents=True)

    remove_request = {
        "schema": "ticketbox-connector-request-v1",
        "profile": "cloudflare-tunnel-v1",
        "action": "remove",
        "operation_id": remove_op_id,
        "install_id": install_id,
        "dataset_id": dataset_id,
        "expected_restore_epoch": 0,
        "release_manifest_sha256": sha_a,
        "expected_revision": 1,
        "expected_credential_generation": 1,
        "expected_enabled": True,
        "expected_public_origin_revision": 2,
        "initiator_sid": "S-1-5-21-1-2-3-1001",
        "desired_enabled": False,
        "closing_operation_id": None,
        "closing_request_hash": None,
    }
    req_hash = hashlib.sha256(
        json.dumps(remove_request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    remove_history = {
        "schema": "ticketbox-lifecycle-operation-v3",
        "kind": "connector",
        "impact": "connector_only",
        "operation_id": remove_op_id,
        "request_hash": req_hash,
        "request": remove_request,
        "phase": "committed",
        "completed_step": "host_applied",
        "result_code": "removed_remote_revocation_pending",
        "replaced_operation": None,
    }
    (history / f"{remove_op_id}.json").write_text(json.dumps(remove_history), encoding="utf-8")

    state_b = {
        "schema": "ticketbox-connector-state-v1",
        "profile": "cloudflare-tunnel-v1",
        "install_id": install_id,
        "dataset_id": dataset_id,
        "expected_restore_epoch": 0,
        "release_manifest_sha256": sha_b,
        "revision": 2,
        "credential_generation": 2,
        "public_origin_revision": 2,
        "enabled": False,
        "configured": False,
        "operation_id": remove_op_id,
        "tunnel_id": None,
    }
    (conn_dir / "state.json").write_text(json.dumps(state_b), encoding="utf-8")

    monkeypatch.setattr(proj_mod.os, "name", "nt")
    monkeypatch.setattr(proj_mod, "DATA_ROOT", data_app)
    monkeypatch.setattr(proj_mod, "runtime_settings_service_owned", lambda: True)
    monkeypatch.setattr(proj_mod, "read_runtime_settings", lambda *_a, **_k: SimpleNamespace(public_origin_revision=2))
    monkeypatch.setattr(
        proj_mod,
        "_read_record",
        lambda path: json.loads(path.read_text(encoding="utf-8")) if path.exists() else None,
    )
    monkeypatch.setattr(
        type(history),
        "glob",
        lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("no FILE_LIST_DIRECTORY")),
    )
    monkeypatch.setenv("TICKETBOX_INSTALLATION_ID", install_id)
    monkeypatch.setenv("TICKETBOX_DATASET_ID", dataset_id)
    monkeypatch.setenv("TICKETBOX_EXPECTED_RESTORE_EPOCH", "0")
    monkeypatch.setenv("TICKETBOX_RELEASE_MANIFEST_SHA256", sha_b)

    with pytest.raises(ConnectorAuthorityError, match="provenance"):
        proj_mod.connector_projection()

    fresh_a = {
        "schema": "ticketbox-lifecycle-operation-v2",
        "operation_id": f"fresh-{sha_a}",
        "kind": "install",
        "request_hash": "1" * 64,
        "target_release_id": "1.2.1",
        "data_root": str(root / "data"),
        "release_manifest_sha256": sha_a,
        "backend_port": 8000,
        "phase": "committed",
        "no_return_point": True,
        "completed_step": "health",
        "install_id": install_id,
        "dataset_id": dataset_id,
        "schema_revision": "20261029_0002",
        "health_attestation_key": "2" * 64,
    }
    upgrade_b = {
        "schema": "ticketbox-lifecycle-operation-v2",
        "operation_id": f"upgrade-{sha_b}",
        "kind": "upgrade",
        "request_hash": "3" * 64,
        "target_release_id": "1.3.0",
        "data_root": str(root / "data"),
        "release_manifest_sha256": sha_b,
        "backend_port": 8000,
        "phase": "committed",
        "no_return_point": True,
        "completed_step": "health",
        "install_id": install_id,
        "dataset_id": dataset_id,
        "schema_revision": "20261101_0001",
        "health_attestation_key": "4" * 64,
        "expected_restore_epoch": 0,
        "previous_release_id": "1.2.1",
        "previous_release_manifest_sha256": sha_a,
        "source_schema_revision": "20261029_0002",
        "backup_path": str(root / "backups" / "pre.tbxcold"),
        "backup_sha256": "5" * 64,
        "business_writes_opened": True,
    }
    (history / f"fresh-{sha_a}.json").write_text(json.dumps(fresh_a), encoding="utf-8")

    incomplete_upgrade = dict(upgrade_b)
    incomplete_upgrade.pop("backup_sha256")
    (history / f"upgrade-{sha_b}.json").write_text(json.dumps(incomplete_upgrade), encoding="utf-8")
    with pytest.raises(ConnectorAuthorityError, match="provenance"):
        proj_mod.connector_projection()

    no_req_hash = dict(upgrade_b)
    no_req_hash.pop("request_hash")
    (history / f"upgrade-{sha_b}.json").write_text(json.dumps(no_req_hash), encoding="utf-8")
    with pytest.raises(ConnectorAuthorityError, match="provenance"):
        proj_mod.connector_projection()

    bool_epoch = dict(upgrade_b)
    bool_epoch["expected_restore_epoch"] = False
    (history / f"upgrade-{sha_b}.json").write_text(json.dumps(bool_epoch), encoding="utf-8")
    with pytest.raises(ConnectorAuthorityError, match="provenance"):
        proj_mod.connector_projection()

    (history / f"upgrade-{sha_b}.json").write_text(json.dumps(upgrade_b), encoding="utf-8")
    projected = proj_mod.connector_projection()
    assert projected["state"] == state_b
    assert projected["operation"] is None
    assert projected["lifecycle_busy"] is False
    assert json.loads((history / f"{remove_op_id}.json").read_text(encoding="utf-8")) == remove_history

    (history / f"{remove_op_id}.json").unlink()
    with pytest.raises(ConnectorAuthorityError, match="missing"):
        proj_mod.connector_projection()
