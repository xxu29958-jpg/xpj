"""Replay frozen native-image OCR through production feedback on owned test PG.

The existing real-db test lane resets identity, financial state and learned
state between baseline, qualified-feedback and withdrawn-feedback arms. Never
point the test contract at a user's installation. Images and reports are local.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from scripts.ocr_benchmark_data import sha256  # noqa: E402
from scripts.ocr_feedback_replay_data import load_replay  # noqa: E402
from scripts.ocr_feedback_replay_metrics import comparison_report  # noqa: E402
from scripts.run_postgres_pytest_lane import build_pytest_command, child_environment  # noqa: E402

MODES = ("baseline", "feedback", "withdrawn")


def source_identity() -> dict:
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=_BACKEND_ROOT, text=True).strip()

    paths = sorted((_BACKEND_ROOT / "scripts").glob("ocr_feedback_replay*.py"))
    paths.append(_BACKEND_ROOT / "tests/test_ocr_feedback_replay.py")
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
        "working_status": git("status", "--porcelain"),
        "replay_sources": {str(path.relative_to(_BACKEND_ROOT)): sha256(path) for path in paths}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path, help="A new directory; prior evidence is never replaced.")
    args = parser.parse_args(argv)
    manifest, output = args.manifest.resolve(), args.output_dir.resolve()
    materials = load_replay(manifest)
    identity = source_identity()
    output.mkdir(parents=True, exist_ok=False)
    environment = child_environment(os.environ)
    environment.update(XPJ_OCR_REPLAY_MANIFEST=str(manifest), XPJ_OCR_REPLAY_OUTPUT=str(output))
    command = list(build_pytest_command(lane="real-db", workers=1))
    command[3] = "tests/test_ocr_feedback_replay.py"
    command.extend(("--junitxml", str(output / "tests.xml")))
    with (output / "tests.log").open("w", encoding="utf-8") as log:
        completed = subprocess.run(command, cwd=_BACKEND_ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
    arms = {mode: json.loads(path.read_text(encoding="utf-8")) for mode in MODES if (path := output / f"{mode}.json").exists()}
    stable = source_identity() == identity
    result = {"schema_version": 1, "source": identity, "source_unchanged": stable,
        "manifest_sha256": sha256(manifest), "inputs": [material.fixture.identity for material in materials],
        "test_exit_code": completed.returncode, "evaluation_completed": completed.returncode == 0 and stable and len(arms) == 3,
        "arms": {mode: sha256(output / f"{mode}.json") for mode in arms},
        "comparison": comparison_report(arms) if len(arms) == 3 else None,
        "product_qualified": False, "human_operations_and_time": "not measured",
        "limitations": ["Amount-only feedback replay, not character recognition or time-role accuracy",
            "Development is sequential prediction then publisher oracle; holdout never writes labels",
            "Declared arrival order, not historical user chronology; transaction/image duplicates rejected",
            "No parser, ranking algorithm, model or scheduling change is estimated by this comparison",
            "Reuses actual native recordings bound by hashes; does not repeat inference",
            "Corpus authorization and model-pretraining limitations remain those of the input manifest"]}
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evaluation_completed": result["evaluation_completed"], "comparison": result["comparison"]}, ensure_ascii=False))
    return 0 if result["evaluation_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
