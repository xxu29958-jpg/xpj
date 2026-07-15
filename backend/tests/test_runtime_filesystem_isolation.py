from __future__ import annotations

from app import config
from app.services import backup_service
from tests._infra.env import TEST_DATA_DIR, TEST_UPLOAD_DIR


def test_writable_runtime_paths_are_process_isolated() -> None:
    assert config.DATA_ROOT == TEST_DATA_DIR
    assert backup_service._BACKUP_DIR == TEST_DATA_DIR / "backups"  # noqa: SLF001
    assert config.get_settings().upload_dir == TEST_UPLOAD_DIR
