"""Per-user Manager ownership and protected instance-proof contracts."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from backend_manager import instance_owner, windows_user_security
from backend_manager.instance_owner import claim_manager_instance


class _FakeOwnership:
    def __init__(self, *, owner: bool) -> None:
        self.owner = owner
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def try_acquire(self) -> bool:
        self.owner = True
        return True


def test_legitimate_second_instance_reads_owners_protected_proof(monkeypatch, tmp_path: Path) -> None:
    handles = [_FakeOwnership(owner=True), _FakeOwnership(owner=False)]
    monkeypatch.setattr(instance_owner, "_instance_root", lambda: tmp_path / "relocated-local-state")
    monkeypatch.setattr(instance_owner, "_claim_os_ownership", lambda *_args: handles.pop(0))

    with claim_manager_instance() as owner:
        assert owner.is_owner is True
        assert owner.secret is not None
        assert len(owner.secret) >= 43
        assert owner.proof_path.is_file()
        owner.publish_port(49152)

        with claim_manager_instance() as second:
            assert second.is_owner is False
            assert second.secret is None
            assert second.read_secret() == owner.secret
            assert second.read_registration() == instance_owner.InstanceRegistration(owner.secret, 49152)
            assert owner.proof_path.is_file()

    assert owner.proof_path.exists() is False


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex contract")
def test_windows_mutex_is_os_backed_and_single_owner() -> None:
    namespace = f"TicketboxManagerTest-{uuid.uuid4().hex}"
    user_sid = windows_user_security.current_user_sid()
    first = instance_owner._windows_mutex(user_sid, namespace=namespace)  # noqa: SLF001
    second = instance_owner._windows_mutex(user_sid, namespace=namespace)  # noqa: SLF001
    try:
        assert first.owner is True
        assert second.owner is False
    finally:
        second.close()
        first.close()
