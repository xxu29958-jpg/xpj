"""Public CLI counterexamples, including the real release aggregator's failure propagation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "backend/scripts"
sys.path.insert(0, str(SCRIPTS))
from error_reporting_contract import REQUIRED_FILES  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _save(repo, path, text):
    destination = repo / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


@pytest.fixture
def guard_repo(tmp_path):
    (tmp_path / "backend/scripts").mkdir(parents=True)
    for path in REQUIRED_FILES:
        _save(tmp_path, path, (ROOT / path).read_text(encoding="utf-8"))
    for name in ("_audit_error_reporting.py", "error_reporting_rules.py", "error_reporting_contract.py",
                 "adr_contract_git.py", "repository_weight_sources.py", "release_audit.py"):
        shutil.copyfile(SCRIPTS / name, tmp_path / "backend/scripts" / name)
    for name in ("_audit_pr_delta_metrics.py", "_audit_repository_weight.py"):
        _save(tmp_path, "backend/scripts/" + name, "raise SystemExit(0)\n")
    _save(tmp_path, "backend/app/ordinary_probe.py", "def handle():\n    return 1\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Reporting Fixture")
    _git(tmp_path, "config", "user.email", "fixture@example.invalid")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "baseline")
    base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "commit", "--allow-empty", "-qm", "candidate")
    return tmp_path, base


def _run(fixture, *, aggregator=False, commit=False, extra=()):
    repo, base = fixture
    if commit:
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "mutant")
    env = {key: value for key, value in os.environ.items()
        if not key.startswith(("GITHUB_", "GITEA_", "XPJ_")) and key != "CI"}
    env["XPJ_AUDIT_BASE_REF"] = base
    entry = "release_audit.py" if aggregator else "_audit_error_reporting.py"
    args = [] if aggregator else ["--worktree"]
    return subprocess.run([sys.executable, str(repo / "backend/scripts" / entry), *args, *extra],
        cwd=repo / "backend", env=env, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("path,content,rule", [
    ("backend/app/new_worker.py", "from threading import Thread as Worker\nWorker(target=lambda: None).start()\n", "independent-execution"),
    ("backend/app/ordinary_probe.py", "def handle():\n    try:\n        return work()\n    except Exception:\n        return None\n", "terminal-catch"),
    ("backend/app/new_output.py", "import logging as log\nlog.basicConfig(filename='other.log')\n", "logging-output"),
    ("backend/app/new_output.py", "import logging\nlogger=logging.getLogger(__name__)\nlogger.propagate=False\n", "logging-output"),
    ("android/app/src/main/java/com/ticketbox/NewProbe.kt", "import android.util.Log as Diagnostic\nfun report() { Diagnostic.w(\"tag\", \"raw\") }", "android-terminal-output"),
])
def test_public_guard_blocks_new_file_and_old_function_boundaries(guard_repo, path, content, rule):
    _save(guard_repo[0], path, content)
    result = _run(guard_repo)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["base"] == guard_repo[1] and report["evidence"] == "working-tree"
    assert any(item["path"] == path and item["rule"] == rule and item["status"] == "NEEDS_REVIEW"
        for item in report["findings"])


def test_registered_handler_and_module_logger_inherit_without_per_feature_registration(guard_repo):
    _save(guard_repo[0], "backend/app/new_handler.py", '''import logging
from app.services.background_task_registry import TaskHandlerRegistry
logger = logging.getLogger(__name__)
def execute(db, task, payload):
    raise RuntimeError("the common runner observes this")
registry = TaskHandlerRegistry({"new_probe": execute})
# Thread(target=unobserved).start(); except Exception: pass
example = "logging.basicConfig(filename='raw.log')"
''')
    result = _run(guard_repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert any(item["path"].endswith("new_handler.py") and item["status"] == "INHERITED"
        for item in json.loads(result.stdout)["findings"])


@pytest.mark.parametrize("target,old,new", [
    ("backend/app/errors.py", "report_http_error(request, 500, error=exc)", "pass"),
    ("android/app/src/main/java/com/ticketbox/data/repository/NetworkErrorHandler.kt",
        "requestId = parsed.requestId", "requestId = null"),
    ("backend/packaging/launch.py", "app.log_sanitize.SanitizedFormatter", "logging.Formatter"),
])
def test_common_owner_and_android_id_loss_are_blocked(guard_repo, target, old, new):
    path = guard_repo[0] / target
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")
    result = _run(guard_repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert any(item["status"] == "VIOLATION" and item["path"] == target
        for item in json.loads(result.stdout)["findings"])


@pytest.mark.parametrize("damage", ["deleted", "wip", "nonzero", "parse"])
def test_real_aggregator_propagates_missing_lane_execution_and_required_parse_failure(guard_repo, damage):
    repo, _base = guard_repo
    entry = repo / "backend/scripts/_audit_error_reporting.py"
    if damage == "deleted":
        entry.unlink()
    elif damage == "wip":
        entry.rename(entry.with_name("_audit_wip_error_reporting.py"))
    elif damage == "nonzero":
        entry.write_text("raise SystemExit(2)\n", encoding="utf-8")
    else:
        _save(repo, "backend/app/errors.py", "def invalid(\n")
    result = _run(guard_repo, aggregator=True, commit=True)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "error-reporting" in result.stdout or "_audit_error_reporting.py" in result.stderr
    if damage == "parse":
        assert "input/parse incomplete" in result.stdout


def test_public_guard_rejects_missing_base_and_identifies_committed_qualification(guard_repo):
    result = _run(guard_repo, extra=("--base", "missing-base"))
    assert result.returncode == 2 and "cannot resolve" in result.stdout
    result = _run(guard_repo, aggregator=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"evidence": "committed-tree"' in result.stdout
    assert '"returncode":0' in result.stdout
