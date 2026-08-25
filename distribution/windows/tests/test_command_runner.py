from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import command
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner


def test_subprocess_timeout_has_a_typed_unknown_outcome(monkeypatch) -> None:
    def time_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("initdb.exe", 180)

    monkeypatch.setattr(command, "_run_process", time_out)

    with pytest.raises(LifecycleError) as caught:
        SubprocessCommandRunner().run(["initdb.exe"], timeout_s=180)

    assert caught.value.code == "command_outcome_unknown"
    assert "180" in caught.value.message


def test_subprocess_start_failure_is_typed(monkeypatch) -> None:
    def fail_to_start(*_args, **_kwargs):
        raise FileNotFoundError("missing executable")

    monkeypatch.setattr(command, "_run_process", fail_to_start)

    with pytest.raises(LifecycleError) as caught:
        SubprocessCommandRunner().run(["missing.exe"])

    assert caught.value.code == "command_start_failed"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_timeout_terminates_a_descendant_that_inherits_the_output_pipe(tmp_path: Path) -> None:
    descendant_pid = tmp_path / "descendant.pid"
    holder = tmp_path / "descendant_holder.py"
    holder.write_text(
        """\
import subprocess
import sys
import time
from pathlib import Path

child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
    stdout=sys.stdout,
    stderr=sys.stderr,
    close_fds=False,
)
Path(sys.argv[1]).write_text(str(child.pid), encoding="ascii")
print(child.pid, flush=True)
time.sleep(60)
""",
        encoding="utf-8",
    )
    lifecycle_root = Path(__file__).resolve().parents[1] / "lifecycle"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(lifecycle_root)
    worker_code = """\
import sys
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner

try:
    SubprocessCommandRunner().run(
        [sys.executable, sys.argv[1], sys.argv[2]],
        timeout_s=1,
    )
except LifecycleError as exc:
    raise SystemExit(0 if exc.code == "command_outcome_unknown" else 3)
raise SystemExit(4)
"""
    worker = subprocess.Popen(
        [sys.executable, "-c", worker_code, str(holder), str(descendant_pid)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = worker.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["taskkill", "/PID", str(worker.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        worker.wait(timeout=10)
        if descendant_pid.is_file():
            subprocess.run(
                ["taskkill", "/PID", descendant_pid.read_text(encoding="ascii"), "/F"],
                capture_output=True,
                check=False,
                timeout=10,
            )
        pytest.fail("command timeout left an inherited pipe open in a descendant")

    assert worker.returncode == 0, f"stdout={stdout!r} stderr={stderr!r}"
