from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "_audit_desktop_dependency_ci.py"


def _load():
    scripts_dir = str(_MODULE_PATH.parent)
    sys.path.insert(0, scripts_dir)
    try:
        spec = importlib.util.spec_from_file_location("_audit_desktop_dependency_ci", _MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(scripts_dir)


def _write_workflow(root: Path, provider: str, command: str) -> Path:
    workflows = root / provider / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(f"jobs:\n  audit:\n    steps:\n      - run: {command}\n", encoding="utf-8")
    return workflows


def test_both_providers_require_live_desktop_pip_audit(tmp_path: Path) -> None:
    mod = _load()
    commands = (
        "python -m pip_audit --strict -r ../desktop/requirements.txt",
        "pip-audit --requirement ../desktop/requirements.txt",
        "pip-audit --requirement=../desktop/requirements.txt",
    )
    for index, command in enumerate(commands):
        dirs = [_write_workflow(tmp_path / str(index), provider, command) for provider in (".github", ".gitea")]
        assert mod.missing_provider_audits(dirs) == []


@pytest.mark.parametrize("missing_provider", [".github", ".gitea"])
def test_each_provider_is_independently_required(tmp_path: Path, missing_provider: str) -> None:
    mod = _load()
    command = "python -m pip_audit --strict -r ../desktop/requirements.txt"
    dirs = [
        _write_workflow(tmp_path, provider, "python -m pytest -q" if provider == missing_provider else command)
        for provider in (".github", ".gitea")
    ]

    assert mod.missing_provider_audits(dirs) == [missing_provider]


def test_non_executing_text_cannot_fake_dependency_audit(tmp_path: Path) -> None:
    mod = _load()
    fakes = (
        'Write-Host "python -m pip_audit -r ../desktop/requirements.txt"',
        '$audit = "python -m pip_audit -r ../desktop/requirements.txt"',
        "if ($false) { python -m pip_audit -r ../desktop/requirements.txt }",
        "python -m pip_audit --ignore-vuln ../desktop/requirements.txt",
    )

    for index, fake in enumerate(fakes):
        dirs = [_write_workflow(tmp_path / str(index), provider, fake) for provider in (".github", ".gitea")]
        assert mod.missing_provider_audits(dirs) == [".github", ".gitea"]
