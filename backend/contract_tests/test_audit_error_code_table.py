from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "_audit_error_code_table.py"


def _load() -> object:
    # Same pattern as test_audit_ci_gap: load straight from the file path so
    # backend/scripts never lands on sys.path for later tests.
    spec = importlib.util.spec_from_file_location("_audit_error_code_table", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_error_code_table_lane_passes_on_real_tree() -> None:
    """Every message-less AppError code in the live tree is in ERROR_MESSAGES
    (the 2026-06-10 audit's not_found / task_not_found gaps are closed)."""
    mod = _load()
    assert len(mod._error_message_keys()) >= 80
    assert mod.main() == 0


def test_error_code_table_lane_catches_a_missing_code(
    tmp_path: Path, monkeypatch,
) -> None:
    """Bite check: a message-less AppError whose code is absent from the table
    must FAIL the lane; an explicit-message call and a covered code must not."""
    mod = _load()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "errors.py").write_text(
        'ERROR_MESSAGES = {\n    "covered": "有文案。",\n    "server_error": "服务器开小差了，请稍后再试。",\n}\n',
        encoding="utf-8",
    )
    (app_dir / "routes.py").write_text(
        "\n".join([
            "def f():",
            '    raise AppError("covered", status_code=404)',          # in table -> ok
            '    raise AppError("orphan_code", status_code=409)',      # missing -> FAIL
            '    raise AppError("also_orphan", "自带文案。", status_code=400)',  # explicit msg -> ok
        ]) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "APP_DIR", app_dir)
    monkeypatch.setattr(mod, "ERRORS_FILE", app_dir / "errors.py")

    assert mod.main() == 1
