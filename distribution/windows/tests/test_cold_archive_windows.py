from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest
from ticketbox_lifecycle import cli
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.windows_cold_file import create_private_archive


def test_private_archive_is_exclusive_from_creation_and_never_overwrites(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("requires real Windows file security")
    if not ctypes.windll.shell32.IsUserAnAdmin():
        if os.environ.get("CI"):
            pytest.fail("Windows cold-copy qualification requires an elevated runner")
        pytest.skip("local shell is not elevated; actual ACL qualification runs on Windows CI")
    output = tmp_path / "private.tbxcold"
    with create_private_archive(output) as target:
        assert native._object_dacl_sddl(output) == native._canonical_dacl_sddl("D:P(A;;FA;;;SY)(A;;FA;;;BA)")
        with pytest.raises(PermissionError):
            output.read_bytes()
        with pytest.raises(PermissionError):
            output.rename(tmp_path / "replaced.tbxcold")
        target.write(b"fixture-only-sensitive-material")
    before = output.read_bytes()
    with pytest.raises(LifecycleError, match="new private"), create_private_archive(output):
        pytest.fail("must not reopen an existing archive for writing")
    assert output.read_bytes() == before


def test_non_elevated_cold_command_refuses_before_accessing_the_installation(tmp_path: Path, capsys) -> None:
    if os.name != "nt" or ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip("requires an ordinary Windows user")
    target = tmp_path / "not-created.tbxcold"
    assert cli.main(["cold-copy", "--output", str(target)]) == 2
    assert "cold_admin_required" in capsys.readouterr().err
    assert not target.exists()
