from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]

_KEY = "a" * 64
_CHALLENGE = "b" * 64
_EXPECTED = "5d5dfb7924f0623a6fde2bf10ee4225ebbe998ec98a49f3729ca534dc7078fe0"


@contextmanager
def _desktop_import_stubs() -> Iterator[None]:
    package = ModuleType("backend_manager")
    package.__path__ = []  # type: ignore[attr-defined]
    version = ModuleType("backend_manager.version_contract")
    version.is_managed_release_version = lambda _value: True  # type: ignore[attr-defined]
    previous = {
        name: sys.modules.get(name)
        for name in ("backend_manager", "backend_manager.version_contract")
    }
    sys.modules["backend_manager"] = package
    sys.modules["backend_manager.version_contract"] = version
    try:
        yield
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


def test_all_three_health_consumers_share_one_exact_attestation_claim() -> None:
    backend = _load(
        ROOT / "backend" / "app" / "services" / "installation_health_attestation.py",
        "ticketbox_backend_health_attestation_test",
    )
    lifecycle = _load(
        ROOT
        / "distribution"
        / "windows"
        / "lifecycle"
        / "ticketbox_lifecycle"
        / "policy"
        / "health_attestation.py",
        "ticketbox_lifecycle_health_attestation_test",
    )
    with _desktop_import_stubs():
        manager = _load(
            ROOT / "desktop" / "backend_manager" / "health_probe.py",
            "ticketbox_manager_health_attestation_test",
        )

    assert backend.sign_health_challenge(_KEY, _CHALLENGE) == _EXPECTED
    assert lifecycle.sign_challenge(_KEY, _CHALLENGE) == _EXPECTED
    assert manager._sign_challenge(_KEY, _CHALLENGE) == _EXPECTED
