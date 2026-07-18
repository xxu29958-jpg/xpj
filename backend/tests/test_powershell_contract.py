from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from scripts import run_packaging_tests

pytestmark = pytest.mark.parallel_safe


def _load_module(relative_path: str, module_name: str) -> ModuleType:
    path = run_packaging_tests.BACKEND_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_contract() -> ModuleType:
    return _load_module(
        "scripts/packaging_powershell_contract.py",
        "xpj_powershell_contract_probe",
    )


def _engine_paths(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "powershell": tmp_path / "WindowsPowerShell" / "powershell.exe",
        "pwsh": tmp_path / "PowerShell" / "pwsh.exe",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return paths


def _stub_probe(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    paths: dict[str, Path],
) -> list[str]:
    commands: list[str] = []
    monkeypatch.setattr(module.shutil, "which", lambda command: str(paths[command]))

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(Path(command[0]).name)
        edition = "Desktop" if Path(command[0]) == paths["powershell"] else "Core"
        version = (5, 1) if edition == "Desktop" else (7, 5)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {"edition": edition, "major": version[0], "minor": version[1]}
            ),
            "",
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    return commands


def _preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[dict[str, Path], str, list[str]]:
    controller = _load_contract()
    paths = _engine_paths(tmp_path)
    commands = _stub_probe(monkeypatch, controller, paths)
    proof = controller.powershell_contract_preflight_proof()
    return paths, proof, commands


def test_powershell_preflight_probes_each_runtime_once_and_workers_reuse_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths, proof, commands = _preflight(monkeypatch, tmp_path)

    assert commands == ["powershell.exe", "pwsh.exe"]
    worker = _load_contract()
    monkeypatch.setattr(worker.shutil, "which", lambda command: str(paths[command]))
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("worker repeated the PowerShell probe"),
    )
    monkeypatch.setenv(worker.POWERSHELL_CONTRACT_PROOF_ENV, proof)

    assert worker.powershell_contract_engines() == [
        str(paths["powershell"].resolve()),
        str(paths["pwsh"].resolve()),
    ]


def test_powershell_worker_rejects_changed_preflight_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths, raw_proof, _commands = _preflight(monkeypatch, tmp_path)
    proof = json.loads(raw_proof)
    proof[1][0] = str(tmp_path / "other-pwsh.exe")
    worker = _load_contract()
    monkeypatch.setattr(worker.shutil, "which", lambda command: str(paths[command]))
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("worker fell back to a runtime probe"),
    )
    monkeypatch.setenv(worker.POWERSHELL_CONTRACT_PROOF_ENV, json.dumps(proof))

    with pytest.raises(AssertionError):
        worker.powershell_contract_engines()


def test_powershell_worker_rejects_malformed_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _load_contract()
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("worker fell back to a runtime probe"),
    )
    monkeypatch.setenv(worker.POWERSHELL_CONTRACT_PROOF_ENV, "{not-json")

    with pytest.raises(AssertionError) as raised:
        worker.powershell_contract_engines()

    assert isinstance(raised.value.__cause__, json.JSONDecodeError)


def test_powershell_worker_rejects_preflight_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths, raw_proof, _commands = _preflight(monkeypatch, tmp_path)
    proof = json.loads(raw_proof)
    proof[1][1] = "Desktop"
    worker = _load_contract()
    monkeypatch.setattr(worker.shutil, "which", lambda command: str(paths[command]))
    monkeypatch.setenv(worker.POWERSHELL_CONTRACT_PROOF_ENV, json.dumps(proof))

    with pytest.raises(AssertionError):
        worker.powershell_contract_engines()


def test_packaging_controller_publishes_preflight_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conftest = _load_module(
        "packaging/tests/conftest.py",
        "xpj_packaging_conftest_powershell_probe",
    )
    monkeypatch.delenv(conftest.POWERSHELL_CONTRACT_PROOF_ENV, raising=False)
    monkeypatch.setattr(
        conftest,
        "powershell_contract_preflight_proof",
        lambda: "controller-proof",
    )

    conftest._prepare_powershell_contract(SimpleNamespace())

    assert (
        conftest.os.environ[conftest.POWERSHELL_CONTRACT_PROOF_ENV]
        == "controller-proof"
    )


def test_packaging_worker_validates_controller_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conftest = _load_module(
        "packaging/tests/conftest.py",
        "xpj_packaging_conftest_worker_success_probe",
    )
    monkeypatch.setenv(conftest.POWERSHELL_CONTRACT_PROOF_ENV, "controller-proof")
    validated: list[None] = []
    monkeypatch.setattr(
        conftest,
        "powershell_contract_engines",
        lambda: validated.append(None) or [],
    )

    conftest._prepare_powershell_contract(
        SimpleNamespace(workerinput={"workerid": "gw0"})
    )

    assert validated == [None]


def test_packaging_worker_rejects_missing_controller_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conftest = _load_module(
        "packaging/tests/conftest.py",
        "xpj_packaging_conftest_missing_proof_probe",
    )
    monkeypatch.delenv(conftest.POWERSHELL_CONTRACT_PROOF_ENV, raising=False)

    with pytest.raises(pytest.UsageError):
        conftest._prepare_powershell_contract(
            SimpleNamespace(workerinput={"workerid": "gw1"})
        )


def test_packaging_worker_rejects_invalid_controller_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conftest = _load_module(
        "packaging/tests/conftest.py",
        "xpj_packaging_conftest_invalid_proof_probe",
    )
    monkeypatch.setenv(conftest.POWERSHELL_CONTRACT_PROOF_ENV, "invalid-proof")
    rejection = AssertionError("invalid proof")

    def reject_proof() -> None:
        raise rejection

    monkeypatch.setattr(conftest, "powershell_contract_engines", reject_proof)

    with pytest.raises(pytest.UsageError) as raised:
        conftest._prepare_powershell_contract(
            SimpleNamespace(workerinput={"workerid": "gw2"})
        )

    assert raised.value.__cause__ is rejection
