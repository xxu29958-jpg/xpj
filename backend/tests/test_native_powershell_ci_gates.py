from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NATIVE_PS_GATE_SCRIPTS = ("check_text_encoding.ps1", "check_dependency_versions.ps1")
_LASTEXITCODE_GUARD = "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"
_ENCODING_GATE_WORKFLOWS = (
    _REPO_ROOT / ".github" / "workflows" / "ci.yml",
    _REPO_ROOT / ".gitea" / "workflows" / "windows-ci.yml",
)


def test_native_ps_gate_calls_are_lastexitcode_guarded() -> None:
    """Every native PowerShell gate call must be immediately exit-code guarded."""
    for workflow in _ENCODING_GATE_WORKFLOWS:
        lines = workflow.read_text(encoding="utf-8").splitlines()
        guarded = 0
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("powershell "):
                continue
            if not any(script in stripped for script in _NATIVE_PS_GATE_SCRIPTS):
                continue
            nxt = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
            assert nxt == _LASTEXITCODE_GUARD, (
                f"{workflow}: native PS gate call on line {idx + 1} ({stripped!r}) "
                f"is not immediately followed by {_LASTEXITCODE_GUARD!r} "
                f"(got {nxt!r}); a failing gate's exit code would be masked."
            )
            guarded += 1
        assert guarded == len(_NATIVE_PS_GATE_SCRIPTS), (
            f"{workflow}: expected {len(_NATIVE_PS_GATE_SCRIPTS)} guarded native PS "
            f"gate calls, found {guarded}; did the gate step change shape?"
        )
