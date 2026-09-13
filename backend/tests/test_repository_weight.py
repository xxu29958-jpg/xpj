"""Real two-commit CLI counterexamples; no database or product runtime is started."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "_audit_repository_weight.py"


def git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        [
            "git", "-c", "user.name=Weight fixture", "-c", "user.email=weight@example.invalid",
            "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={repo / 'no-hooks'}", *arguments,
        ],
        cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return result.stdout.strip()


def commit_files(repo: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--quiet", "-b", "main")
    return root


def run_weight(repo: Path, base: str, head: str, tmp_path: Path) -> tuple[subprocess.CompletedProcess, dict]:
    output = tmp_path / "weight.json"
    result = subprocess.run(
        [sys.executable, str(ENTRY), "--repo", str(repo), "--base", base, "--head", head, "--json", str(output)],
        env={key: value for key, value in os.environ.items() if key != "GITHUB_STEP_SUMMARY"},
        capture_output=True, text=True, encoding="utf-8",
    )
    report = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    return result, report


def test_whole_repository_totals_use_exact_blobs_and_count_each_file_once(repo, tmp_path) -> None:
    base = commit_files(repo, {
        "backend/app/service.py": "def answer():\n    return 1\n",
        "backend/migrations/versions/initial.py": "SCHEMA = 1\n",
        "android/app/src/main/java/View.kt": "// view\n\nval value = 1\n",
        "backend/app/templates/web/home.html": "<!-- layout -->\n<div>ok</div>\n",
        "desktop/backend_manager/app.py": "VALUE = 1\n",
        "distribution/windows/runtime/start.ps1": "# runtime\nWrite-Output 'ready'\n",
        "backend/tests/test_app.py": "assert True\n",
        "backend/packaging/tests/test_build.py": "assert True\n",
        "android/app/src/test/java/Test.kt": "val test = 1\n",
        "android/app/src/androidTest/java/Device.kt": "val device = 1\n",
        "desktop/tests/test_app.py": "assert True\n",
        "distribution/windows/tests/test_install.py": "assert True\n",
        "backend/scripts/helper.py": "VALUE = 1\n",
        "docs/design.py": "# not source scope\n" * 1001,
        "android/app/schemas/schema.json": "{}\n" * 1001,
        "android/app/build/generated/Generated.kt": "val generated = 1\n" * 1001,
        "backend/app/static/vendor/library.js": "const vendor = 1;\n" * 1001,
        "desktop/requirements-build.lock": "locked\n" * 1001,
    }, "base")
    head = commit_files(repo, {"backend/app/static/ready.js": "const ready = true;\n"}, "consumer")
    (repo / "android/app/src/main/java/View.kt").write_text("dirty\n" * 1002, encoding="utf-8")
    (repo / "backend/app/untracked.py").write_text("untracked\n" * 1002, encoding="utf-8")

    result, report = run_weight(repo, base, head, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["base"]["sha"] == base
    assert report["current"]["sha"] == head
    assert report["current"]["totals"] == {
        "production_loc": 12, "test_loc": 6, "tooling_loc": 1,
        "executable_total": 18, "source_total": 19,
    }
    assert report["delta"]["production_loc"] == 1
    assert report["current"]["modules"]["Migrations"]["production"] == 1
    assert report["current"]["modules"]["Web"]["production"] == 3
    assert report["current"]["modules"]["Backend"]["files"] == 3
    assert report["current"]["languages"]["Kotlin"]["production"] == 3
    assert report["current"]["languages"]["Kotlin"]["test"] == 2
    view = next(row for row in report["current"]["files"] if row["path"].endswith("/View.kt"))
    assert (view["loc"], view["code"], view["comment"], view["blank"]) == (3, 1, 1, 1)
    assert report["current"]["debt"]["files_over_500"] == 0
    assert report["verdict"] == "HEALTHY GROWTH"


@pytest.mark.parametrize("limit,old_lines,new_lines,delta", [
    (500, 450, 501, -398), (800, 750, 801, -698), (1000, 950, 1001, -898),
])
def test_large_file_growth_stays_visible_for_review_even_when_total_loc_decreases(repo, tmp_path, limit, old_lines, new_lines, delta) -> None:
    base = commit_files(repo, {
        "backend/app/static/a.js": "const a = 1;\n" * old_lines,
        "backend/app/static/b.js": "const b = 1;\n" * old_lines,
    }, "base")
    head = commit_files(repo, {
        "backend/app/static/a.js": "const a = 1;\n" * new_lines,
        "backend/app/static/b.js": "const b = 1;\n",
    }, "concentrated source")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["delta"]["production_loc"] == delta
    assert report["current"]["debt"][f"files_over_{limit}"] == 1
    assert report["failures"] == []
    assert f"files_over_{limit}" in "\n".join(report["advisories"])
    assert "Size changes requiring review" in result.stdout
    assert report["verdict"] != "HEALTHY GROWTH"


def test_real_c901_cannot_be_hidden_by_a_new_noqa(repo, tmp_path) -> None:
    base = commit_files(repo, {"backend/app/branch.py": "def branch(value):\n    return value\n"}, "base")
    branches = "".join(f"    if value == {number}:\n        return {number}\n" for number in range(16))
    head = commit_files(repo, {
        "backend/app/branch.py": "def branch(value):  # noqa: C901\n" + branches + "    return 0\n",
    }, "hidden complexity")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert report["current"]["debt"]["python_c901:Backend:production"] == 1
    assert report["new_suppressions"] == 1


@pytest.mark.parametrize("issue_count", [2, 3])
def test_android_recorded_debt_does_not_grow(repo, tmp_path, issue_count) -> None:
    def baseline(count: int) -> str:
        ids = "".join(f"<ID>LongMethod:View.kt:fun view{number}</ID>" for number in range(count))
        return f"<SmellBaseline><ManuallySuppressedIssues/><CurrentIssues>{ids}</CurrentIssues></SmellBaseline>"

    path = "android/app/detekt-baseline-grayDebug.xml"
    base = commit_files(repo, {path: baseline(2), "android/app/src/main/java/View.kt": "val view = 1\n"}, "base")
    head = commit_files(repo, {path: baseline(issue_count)}, "recorded debt")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == (1 if issue_count == 3 else 0), result.stdout + result.stderr
    assert report["current"]["debt"]["android_detekt:production"] == issue_count
    assert all(row["path"] != path for row in report["current"]["files"])


def test_quoted_suppression_examples_are_not_real_directives(repo, tmp_path) -> None:
    base = commit_files(repo, {"backend/app/example.py": "VALUE = 1\n"}, "base")
    head = commit_files(repo, {
        "backend/app/example.py": 'EXAMPLE = "# noqa: C901"\n',
        "android/app/src/main/java/Example.kt": 'val example = "@Suppress(\\"TooManyFunctions\\")"\n',
        "backend/app/static/example.js": 'const example = "// eslint-disable";\n',
    }, "quoted examples")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["new_suppressions"] == 0


def test_missing_exact_base_does_not_become_a_healthy_empty_report(repo, tmp_path) -> None:
    head = commit_files(repo, {"backend/app/app.py": "VALUE = 1\n"}, "head")
    result, report = run_weight(repo, "1" * 40, head, tmp_path)
    assert result.returncode != 0
    assert "cannot resolve exact base" in result.stderr
    assert "HEALTHY GROWTH" not in result.stdout
    assert not report


@pytest.mark.parametrize("path,source", [
    ("android/app/src/main/java/Example.kt", '@Suppress(\n    "TooManyFunctions",\n)\nval example = 1\n'),
    ("backend/app/static/example.js", "// eslint-disable-next-line no-alert\nalert('fixture');\n"),
    ("backend/app/static/example.css", "/* stylelint-disable color-no-invalid-hex */\na { color: red; }\n"),
    ("android/app/src/main/res/layout/example.xml", '<View tools:ignore="HardcodedText" />\n'),
    ("distribution/windows/runtime/example.ps1", '[System.Diagnostics.CodeAnalysis.SuppressMessageAttribute("PSUseShouldProcess", "")]\nparam()\n'),
])
def test_real_cross_language_suppressions_fail_the_gate(repo, tmp_path, path, source) -> None:
    base = commit_files(repo, {"backend/app/app.py": "VALUE = 1\n"}, "base")
    head = commit_files(repo, {path: source}, "suppressed consumer")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert report["new_suppressions"] == 1
    assert report["added_suppression_records"][0]["path"] == path


def test_ci_output_targets_receive_the_same_report(repo, tmp_path) -> None:
    base = commit_files(repo, {"backend/app/app.py": "VALUE = 1\n"}, "base")
    head = commit_files(repo, {"backend/app/app.py": "VALUE = 2\n"}, "head")
    output, summary = tmp_path / "ci-weight.json", tmp_path / "ci-summary.md"
    result = subprocess.run(
        [sys.executable, str(ENTRY), "--repo", str(repo), "--base", base, "--head", head],
        env={**os.environ, "XPJ_CODEBASE_WEIGHT_JSON": str(output), "GITHUB_STEP_SUMMARY": str(summary)},
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.is_file(), "CI needs the immutable structured report"
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["current"]["sha"] == head
    assert report["changes"] == [{
        "path": "backend/app/app.py", "change": "modified", "modules": ["Backend"], "loc_delta": 0,
    }]
    assert "CODEBASE WEIGHT" in summary.read_text(encoding="utf-8")
    assert head in summary.read_text(encoding="utf-8")


def test_android_rule_exemption_cannot_hide_complexity(repo, tmp_path) -> None:
    path = "android/detekt.yml"
    policy = yaml.safe_load((ENTRY.parents[2] / path).read_text(encoding="utf-8"))
    base = commit_files(repo, {path: yaml.safe_dump(policy)}, "maintained policy")
    policy["complexity"]["CyclomaticComplexMethod"]["ignoreSingleWhenExpression"] = True
    head = commit_files(repo, {path: yaml.safe_dump(policy)}, "broader rule exemption")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "changed Android complexity exemptions" in "\n".join(report["failures"])


def test_inno_source_lines_and_malformed_debt_metadata(repo, tmp_path) -> None:
    base = commit_files(repo, {
        "distribution/windows/installer/example.iss": "; installer\n[Setup]\nAppName=Fixture\n\n",
    }, "installer source")
    result, report = run_weight(repo, base, base, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    record = report["current"]["files"][0]
    assert record["language"] == "Inno Setup"
    assert (record["loc"], record["code"], record["comment"], record["blank"]) == (4, 2, 1, 1)
    head = commit_files(repo, {"android/app/detekt-baseline-grayDebug.xml": "<broken>"}, "unreadable debt")
    failure = subprocess.run(
        [sys.executable, str(ENTRY), "--repo", str(repo), "--base", base, "--head", head],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert failure.returncode == 2
    assert "CODEBASE WEIGHT INCOMPLETE" in failure.stderr
    assert "HEALTHY" not in failure.stdout


def test_fixture_reports_do_not_pollute_the_real_ci_summary(repo, tmp_path, monkeypatch) -> None:
    summary = tmp_path / "real-ci-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    head = commit_files(repo, {"backend/app/app.py": "VALUE = 1\n"}, "fixture")
    result, _ = run_weight(repo, head, head, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not summary.exists(), "Synthetic repositories must not enter the real CI report"


@pytest.mark.parametrize("path,language,source", [
    ("backend/app/static/branch.js", "JavaScript", "function branch(value) {\n%s\n}"),
    ("android/app/src/main/java/Branch.kt", "Kotlin", "fun branch(value: Int): Int {\n%s\n}"),
    ("backend/app/static/branch.ts", "TypeScript", "function branch(value: number) {\n%s\n}"),
    ("desktop/backend_manager/ui.html", "JavaScript", "<html>\n<script>function branch(value) {\n%s\n}</script>\n</html>"),
])
def test_function_map_finds_actual_complex_consumers(repo, tmp_path, path, language, source) -> None:
    base = commit_files(repo, {path: "\n"}, "empty consumer")
    body = "\n".join(f"if (value == {index}) return {index};" for index in range(16))
    head = commit_files(repo, {path: source % body}, "complex consumer")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    functions = report["current"]["functions"]
    branch = next(row for row in functions if row["name"] == "branch")
    assert (branch["path"], branch["language"], branch["metric"], branch["complexity"]) == (
        path, language, "lizard_ccn", 17,
    )
    assert branch["line"] == (2 if path.endswith(".html") else 1)
    assert "Complex function hotspots" in result.stdout
    assert report["tools"]["lizard"] == "1.24.0"


@pytest.mark.parametrize("body_lines", [1, 81])
def test_kotlin_annotation_target_is_not_a_function_and_real_spans_remain_reviewable(repo, tmp_path, body_lines):
    path = "android/app/src/test/java/CurrencyTest.kt"
    base = commit_files(repo, {path: "\n"}, "empty")
    body = "    println(value)\n" * body_lines
    source = ("class CurrencyTest {\n    @get:Rule val compose = createComposeRule()\n"
              "    fun render(value: Int) {\n        val label = context.getString(1)\n" + body +
              "    }\n" + "\n" * 85 + "}\n")
    head = commit_files(repo, {path: source}, "annotated Kotlin test")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    functions = report["current"]["functions"]
    assert [row["name"] for row in functions] == ["render"]
    assert functions[0]["line"] == 3
    assert functions[0]["length"] == body_lines + 3
    assert bool(report["advisories"]) == (body_lines > 80)
    assert report["failures"] == []


def test_kotlin_real_getter_keeps_its_complexity_and_location(repo, tmp_path):
    path = "android/app/src/main/java/Fixture.kt"
    base = commit_files(repo, {path: "\n"}, "empty")
    body = "\n".join(f"if (value == {index}) return {index}" for index in range(16))
    source = "class Fixture(val value: Int) {\n    val size: Int\n    get() {\n" + body + "\nreturn 0\n}\n}\n"
    head = commit_files(repo, {path: source}, "real getter")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    getters = [row for row in report["current"]["functions"] if row["name"] == "get"]
    assert len(getters) == 1
    assert (getters[0]["line"], getters[0]["complexity"]) == (3, 17)


def test_powershell_ast_measures_functions_without_executing_source(repo, tmp_path) -> None:
    path = "distribution/windows/runtime/branch.ps1"
    base = commit_files(repo, {path: "# empty\n"}, "empty script")
    branches = "\n".join(f"if ($Value -eq {index}) {{ return {index} }}" for index in range(16))
    head = commit_files(repo, {path: "throw 'MUST NOT EXECUTE'\nfunction Branch($Value) {\n" + branches + "\n}\n"}, "complex script")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    branch = next(row for row in report["current"]["functions"] if row["name"] == "Branch")
    assert (branch["line"], branch["metric"], branch["complexity"]) == (2, "powershell_ast_decisions", 17)


def test_inno_routine_decisions_ignore_literals_and_external_declarations(repo, tmp_path) -> None:
    path = "distribution/windows/installer/branch.iss"
    base = commit_files(repo, {path: "; empty\n"}, "empty installer")
    body = "\n".join(f"if Value = {index} then Result := {index};" for index in range(16))
    source = "function ExternalFoo: Boolean; external 'Foo@fixture.dll';\nfunction Branch(Value: Integer): Integer;\nbegin\n"
    source += "// if while case\nMessage := 'if while case';\n" + body + "\nend;\n"
    head = commit_files(repo, {path: source}, "complex routine")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    functions = report["current"]["functions"]
    assert [row["name"] for row in functions] == ["Branch"]
    assert (functions[0]["line"], functions[0]["metric"], functions[0]["complexity"]) == (
        2, "inno_decision_tokens", 16,
    )


def test_powershell_batch_keeps_separate_script_parameter_blocks(repo, tmp_path) -> None:
    head = commit_files(repo, {
        "scripts/one.ps1": "param([string]$Value)\nfunction First { return 1 }\n",
        "scripts/two.ps1": "param([string]$Value)\nfunction Second { return 2 }\n",
    }, "two independent scripts")
    result, report = run_weight(repo, head, head, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert {row["name"] for row in report["current"]["functions"]} == {"<script>", "First", "Second"}


def test_real_node_fixture_and_deployed_edge_source_are_counted(repo, tmp_path) -> None:
    base = commit_files(repo, {"backend/app/app.py": "VALUE = 1\n"}, "base")
    head = commit_files(repo, {
        "backend/tests/fixtures/check.cjs": "module.exports = () => true;\n",
        "infra/cloudflare/public-surface-rate-limit/src/index.ts": "export default {};\n",
        "infra/cloudflare/public-surface-rate-limit/wrangler.jsonc": '{"main":"src/index.ts"}\n',
        "backend/alembic.ini": "[alembic]\n",
        "android/gradle.properties": "org.gradle.jvmargs=-Xmx2g\n",
        "android/app/compose_stability_config.conf": "kotlin.collections.*\n",
    }, "actual executable inputs")
    result, report = run_weight(repo, base, head, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["delta"]["test_loc"] == 1
    assert report["delta"]["production_loc"] == 1
    assert report["current"]["modules"]["Public edge"]["production"] == 1
    assert report["delta"]["tooling_loc"] == 4


def test_release_audit_rejects_missing_repository_weight_lane(tmp_path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(ENTRY.parent))
    import release_audit

    (tmp_path / "_audit_pr_delta_metrics.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="_audit_repository_weight.py"):
        release_audit._discover_lanes(tmp_path)
