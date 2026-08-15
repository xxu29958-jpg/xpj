from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
BACKEND = PACKAGING.parent


def test_c07_writer_fence_commits_all_effective_writer_authorities() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in (
            PACKAGING / "postgresql_writer_fence" / "primitives.ps1",
            PACKAGING / "postgresql_writer_fence" / "observation_query.ps1",
            PACKAGING / "postgresql_writer_fence" / "precondition_guard.ps1",
            PACKAGING / "postgresql_writer_fence" / "session_drain.ps1",
            PACKAGING / "postgresql_writer_fence" / "reconciler.ps1",
            PACKAGING / "c07_lifecycle" / "writer_fence" / "policy.ps1",
            PACKAGING / "c07_lifecycle" / "writer_fence" / "adapter.ps1",
        )
    )
    database_source = (PACKAGING / "windows_c07_database.ps1").read_text(
        encoding="utf-8-sig"
    )

    for required in (
        "pg_try_advisory_lock(",
        "SELECT pg_stat_clear_snapshot();",
        "has_database_privilege(",
        "has_schema_privilege(",
        "has_table_privilege(",
        "has_sequence_privilege(",
        "pg_has_role(",
        "current_setting('max_prepared_transactions')",
        "FROM pg_prepared_xacts",
        "FROM pg_subscription",
        "logical replication worker",
        "unexpected_database_worker_count",
        "inert_unregistered",
        "can_assume_write_owner",
        "owns_security_definer_routines",
        "can_execute_unowned_security_definer_routines",
    ):
        assert required in source
    assert '"--quiet",' in database_source
    assert "pg_terminate_backend(\n                fence_pid," in source
    assert "$TerminationTimeoutMilliseconds" in source
    assert "database_lock.locktype = 'object'" in source
    assert "database_lock.classid = 'pg_database'::regclass::oid" in source
    assert "Enter-TicketboxC07CurrentWriterDatabaseFence" in source
