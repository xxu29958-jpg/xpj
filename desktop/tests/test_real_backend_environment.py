"""The real backend receives its test database authority without host overrides."""

import io
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

from tests import _real_backend


def test_backend_child_keeps_the_passfile_without_ambient_libpq_overrides(monkeypatch, tmp_path):
    overrides = {
        "PGPASSWORD": "unrelated-host-password",
        "PGUSER": "unrelated-host-user",
        "PGSERVICE": "unrelated-host-service",
        "PGSERVICEFILE": "unrelated-host-service.conf",
        "PGHOST": "unrelated-host",
        "PGOPTIONS": "-csearch_path=unrelated",
    }
    authority = {
        "PGPASSFILE": str(tmp_path / "authorized.pgpass"),
        "SMOKE_DATABASE_URL": "explicit-test-smoke-route",
        "XPJ_TEST_CLUSTER_IDENTITY": "explicit-test-cluster",
    }
    for key, value in (overrides | authority).items():
        monkeypatch.setenv(key, value)
    seed = {
        "pairing_code": "test-code",
        "app_token": "test-token",
        "account_name": "test-owner",
        "owner_ledger_id": "test-ledger",
        "other_ledger_id": "other-ledger",
    }
    process = Mock(stdout=io.StringIO("E2E_SEED " + json.dumps(seed) + "\n"))
    launch = Mock(return_value=process)
    monkeypatch.setattr(_real_backend.subprocess, "Popen", launch)
    monkeypatch.setattr(_real_backend, "_backend_python", lambda: "test-python")
    monkeypatch.setattr(_real_backend, "_free_port", lambda: 12345)
    monkeypatch.setattr(_real_backend, "_wait_for_health", lambda *_args: None)
    fixture = _real_backend.real_backend.__wrapped__(SimpleNamespace(mktemp=lambda _name: tmp_path))
    try:
        assert next(fixture).owner_ledger_id == "test-ledger"
        child = launch.call_args.kwargs["env"]
        leaked_keys = sorted(set(child) & set(overrides))
        assert leaked_keys == []
        assert {key: child[key] for key in authority} == authority
        assert child["UPLOAD_DIR"] == str(tmp_path / "uploads")
        assert child["XPJ_E2E_BACKEND_PORT"] == "12345"
        assert all(os.environ[key] == value for key, value in overrides.items())
    finally:
        fixture.close()
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=10)
