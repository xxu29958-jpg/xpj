"""The real backend receives its test database authority without host overrides."""

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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


class _StoppedBeforeDatabaseError(RuntimeError):
    pass


@pytest.fixture
def helper_authority_probe(monkeypatch, tmp_path):
    # Importing the subprocess helper selects its backend working directory.
    monkeypatch.chdir(Path.cwd())
    monkeypatch.syspath_prepend(str(_real_backend._REPO_ROOT / "backend"))
    from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT, TestPostgresContract

    from tests import _real_backend_helper

    # Substitute the already-owned cluster marker; this probe never creates or connects to PostgreSQL.
    identity = TEST_POSTGRES_CONTRACT.database_identity("11111111-1111-4111-8111-111111111111")
    monkeypatch.setattr(TestPostgresContract, "local_database_identity", lambda _self, _port: identity)
    monkeypatch.setattr(TestPostgresContract, "default_data_dir", lambda _self, _port: tmp_path / "owned-local-pg")

    for key in ("DATABASE_URL", "SMOKE_DATABASE_URL", "XPJ_TEST_CLUSTER_IDENTITY", "PGPASSFILE"):
        # Register restoration even when the parent lacks the key: main writes these directly.
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("XPJ_E2E_BACKEND_PORT", "12345")
    observed = {}

    def stop_before_database(url, **kwargs):
        observed.update(url=url, identity=kwargs["cluster_identity"], passfile=kwargs["passfile"],
                        backend_passfile=os.environ.get("PGPASSFILE"))
        raise _StoppedBeforeDatabaseError

    # The Desktop unit lane does not install server/SQL packages. Stop at that
    # adapter boundary; the separate Windows live lane exercises the real lease.
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "scripts.test_postgres_database",
                        SimpleNamespace(dedicated_test_database_lease=stop_before_database))
    return _real_backend_helper, observed


@pytest.mark.parametrize("explicit", [False, True])
def test_helper_selects_one_complete_database_authority(helper_authority_probe, monkeypatch, tmp_path, explicit):
    from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
    from scripts.write_test_postgres_env import render_environment

    helper, observed = helper_authority_probe
    monkeypatch.setenv("PGPASSFILE", str(tmp_path / "ambient.pgpass"))
    expected = render_environment(
        host="localhost", port=TEST_POSTGRES_CONTRACT.ports.local, admin_user="postgres",
        application_user=TEST_POSTGRES_CONTRACT.application_role,
        passfile=TEST_POSTGRES_CONTRACT.default_data_dir(TEST_POSTGRES_CONTRACT.ports.local)
        / TEST_POSTGRES_CONTRACT.passfile_name,
        cluster_identity=TEST_POSTGRES_CONTRACT.local_database_identity(TEST_POSTGRES_CONTRACT.ports.local),
    )
    if explicit:
        expected = {
            "SMOKE_DATABASE_URL": "explicit-test-route", "XPJ_TEST_CLUSTER_IDENTITY": "explicit-test-cluster",
            "PGPASSFILE": str(tmp_path / "authorized.pgpass"),
        }
        for key, value in expected.items():
            monkeypatch.setenv(key, value)

    with pytest.raises(_StoppedBeforeDatabaseError):
        helper.main()

    assert observed == {
        "url": expected["SMOKE_DATABASE_URL"], "identity": expected["XPJ_TEST_CLUSTER_IDENTITY"],
        "passfile": expected["PGPASSFILE"], "backend_passfile": expected["PGPASSFILE"],
    }


@pytest.mark.parametrize("provided", [
    {"SMOKE_DATABASE_URL": "explicit-test-route"},
    {"XPJ_TEST_CLUSTER_IDENTITY": "explicit-test-cluster"},
    {"SMOKE_DATABASE_URL": "explicit-test-route", "XPJ_TEST_CLUSTER_IDENTITY": "explicit-test-cluster"},
])
def test_helper_rejects_partial_authority_before_database_access(helper_authority_probe, monkeypatch, provided):
    helper, observed = helper_authority_probe
    for key, value in provided.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(ValueError, match="complete"):
        helper.main()

    assert observed == {}
