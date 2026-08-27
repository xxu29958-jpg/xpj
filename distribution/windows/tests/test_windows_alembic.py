from __future__ import annotations

from dataclasses import replace

import pytest
from fakes import make_install_request
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.policy.postgres_roles import expected_alembic_probe
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.windows_alembic import WindowsAlembicAdapter


class _ProbeRunner:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.input_text: str | None = None

    def run(
        self,
        argv,
        *,
        env=None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> CompletedCommand:
        del env, timeout_s
        self.input_text = input_text
        return CompletedCommand(tuple(str(part) for part in argv), 0, self.stdout, "")


@pytest.mark.parametrize(
    "observed",
    (
        "20260821_0001-extra",
        "20260821_0001\n20260820_0001",
        f"{expected_alembic_probe()}-extra",
        f"{expected_alembic_probe()}\nsecond-result",
    ),
)
def test_alembic_verify_rejects_non_exact_revision_state(tmp_path, observed: str) -> None:
    request = replace(
        make_install_request(tmp_path),
        schema_revision="20260821_0001",
    )

    with pytest.raises(LifecycleError, match="exact release target"):
        WindowsAlembicAdapter(_ProbeRunner(observed)).verify(request, "alembic")


@pytest.mark.parametrize(
    "observed",
    (
        expected_alembic_probe(),
        f"SET\n{expected_alembic_probe()}\n",
    ),
)
def test_alembic_verify_accepts_only_closed_exact_probe(tmp_path, observed: str) -> None:
    request = replace(
        make_install_request(tmp_path),
        schema_revision="20260821_0001",
    )

    runner = _ProbeRunner(observed)

    WindowsAlembicAdapter(runner).verify(request, "alembic")

    assert runner.input_text is not None
    assert "count(*) = 1" in runner.input_text
    assert "min(version_num) = '20260821_0001'" in runner.input_text
    assert "max(version_num) = '20260821_0001'" in runner.input_text
