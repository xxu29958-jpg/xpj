"""File-identity attacks against complete dataset original capture."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.errors import AppError
from app.services.dataset_originals_adapter import OriginalReference, copy_complete_originals
from app.services.stable_file_reader import hold_stable_file_for_read


def _reference(path: Path) -> tuple[OriginalReference, ...]:
    return (
        OriginalReference(
            tenant_id="owner",
            storage_reference="uploads/owner/receipt.png",
            expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        ),
    )


def test_complete_originals_reject_an_outside_hardlink(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    original = uploads / "owner" / "receipt.png"
    outside = tmp_path / "outside.png"
    original.parent.mkdir(parents=True)
    outside.write_bytes(b"shared-file-identity")
    os.link(outside, original)
    staging = tmp_path / "generation"
    staging.mkdir()

    with pytest.raises(AppError) as rejected:
        copy_complete_originals(
            upload_root=uploads.resolve(),
            destination=staging / "originals",
            references=_reference(outside),
        )

    assert rejected.value.error == "backup_incomplete"


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS directory junction contract")
def test_complete_originals_reject_an_in_root_junction(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    target = uploads / "real"
    target.mkdir(parents=True)
    original = target / "receipt.png"
    original.write_bytes(b"junction-backed-original")
    junction = uploads / "owner"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    staging = tmp_path / "generation"
    staging.mkdir()
    try:
        with pytest.raises(AppError) as rejected:
            copy_complete_originals(
                upload_root=uploads.resolve(),
                destination=staging / "originals",
                references=_reference(original),
            )
        assert rejected.value.error == "backup_incomplete"
    finally:
        if os.path.lexists(junction):
            os.rmdir(junction)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows share-mode contract")
def test_stable_original_handle_blocks_same_path_swap(tmp_path: Path) -> None:
    original = tmp_path / "receipt.png"
    replacement = tmp_path / "replacement.png"
    original.write_bytes(b"stable-original")
    replacement.write_bytes(b"stable-original")

    with hold_stable_file_for_read(original.resolve()) as stream:
        with pytest.raises(OSError):
            os.replace(replacement, original)
        assert stream.read() == b"stable-original"

    os.replace(replacement, original)
    assert original.read_bytes() == b"stable-original"
