from __future__ import annotations

import os
from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.runtime import windows_security_native as native


def test_protected_directory_rejects_untrusted_owner_before_acl_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "operation-root"
    path.mkdir()
    acl_read = {"called": False}
    monkeypatch.setattr(native, "file_owner_sid", lambda _path: "S-1-5-21-9-9-9-1002")

    def read_acl(_path: Path) -> str:
        acl_read["called"] = True
        return "trusted"

    monkeypatch.setattr(native, "_directory_security_sddl", read_acl)

    with pytest.raises(LifecycleViolation, match="untrusted lifecycle directory") as caught:
        native.require_protected_directory(path, code="operation_store_untrusted")

    assert caught.value.code == "operation_store_untrusted"
    assert acl_read["called"] is False


def test_protected_directory_requires_the_exact_lifecycle_dacl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "operation-root"
    path.mkdir()
    expected = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
    monkeypatch.setattr(native, "file_owner_sid", lambda _path: native.ADMINISTRATORS_SID)
    monkeypatch.setattr(native, "_canonical_lifecycle_directory_sddl", lambda: expected)
    monkeypatch.setattr(native, "_directory_security_sddl", lambda _path: expected)

    native.require_protected_directory(path, code="operation_store_untrusted")

    monkeypatch.setattr(
        native,
        "_directory_security_sddl",
        lambda _path: expected + "(A;OICI;FA;;;S-1-5-21-9-9-9-1002)",
    )
    with pytest.raises(LifecycleViolation, match="untrusted lifecycle directory"):
        native.require_protected_directory(path, code="operation_store_untrusted")


@pytest.mark.skipif(os.name != "nt", reason="Windows SDDL conversion")
def test_lifecycle_directory_sddl_is_valid_and_canonical() -> None:
    assert native._LIFECYCLE_DIRECTORY_SDDL.startswith("O:BA")
    assert native._canonical_lifecycle_directory_sddl() == (
        "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
    )
