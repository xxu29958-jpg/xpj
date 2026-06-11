from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "_audit_error_copy_three_surface.py"


def _load() -> object:
    # Same pattern as test_audit_error_code_table: load straight from the file
    # path so backend/scripts never lands on sys.path for later tests.
    spec = importlib.util.spec_from_file_location("_audit_error_copy_three_surface", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Minimal consistent five-piece kit: "alpha" is mapped on every surface with
# Android copy that intentionally diverges from the backend table (legal — the
# repository arm is the Android-canonical divergence point, C6 pins it to
# strings.xml); "beta" is mapped only in ErrorUiText, so its resource must
# mirror the backend message verbatim (C7).
_ERRORS_PY = 'ERROR_MESSAGES = {\n    "alpha": "甲后端文案。",\n    "beta": "乙文案。",\n}\n'

_STRINGS_XML = (
    "<resources>\n"
    '    <string name="error_alpha">甲安卓文案。</string>\n'
    '    <string name="error_beta">乙文案。</string>\n'
    "</resources>\n"
)

_UITEXT_KT = (
    "private fun errorCodeStringRes(code: String?): Int? = when (code) {\n"
    '    "alpha" -> R.string.error_alpha\n'
    '    "beta" -> R.string.error_beta\n'
    "    else -> null\n"
    "}\n"
)

_REPO_KT = (
    "internal fun backendErrorUserMessage(errorCode: String, serverMessage: String): String {\n"
    "    return when (errorCode.trim()) {\n"
    '        "alpha" -> "甲安卓文案。"\n'
    "        else -> serverMessage\n"
    "    }\n"
    "}\n"
)

_MAPPING_MD = (
    "### alpha\n\n"
    "| 字段 | 内容 |\n"
    "|:---|:---|\n"
    "| 用户文案 | 甲安卓文案。 |\n\n"
    "### beta\n\n"
    "| 字段 | 内容 |\n"
    "|:---|:---|\n"
    "| 用户文案 | 乙文案。 |\n"
)


def _install_fixture(
    mod: object,
    base: Path,
    monkeypatch,
    *,
    errors_py: str = _ERRORS_PY,
    strings_xml: str = _STRINGS_XML,
    uitext_kt: str = _UITEXT_KT,
    repo_kt: str = _REPO_KT,
    mapping_md: str = _MAPPING_MD,
) -> None:
    app_dir = base / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "errors.py").write_text(errors_py, encoding="utf-8")
    (base / "strings.xml").write_text(strings_xml, encoding="utf-8")
    (base / "ErrorUiText.kt").write_text(uitext_kt, encoding="utf-8")
    (base / "_RepositorySupport.kt").write_text(repo_kt, encoding="utf-8")
    (base / "mapping.md").write_text(mapping_md, encoding="utf-8")
    monkeypatch.setattr(mod, "APP_DIR", app_dir)
    monkeypatch.setattr(mod, "ERRORS_FILE", app_dir / "errors.py")
    monkeypatch.setattr(mod, "STRINGS_XML", base / "strings.xml")
    monkeypatch.setattr(mod, "ERROR_UITEXT_KT", base / "ErrorUiText.kt")
    monkeypatch.setattr(mod, "REPO_SUPPORT_KT", base / "_RepositorySupport.kt")
    monkeypatch.setattr(mod, "MAPPING_MD", base / "mapping.md")
    monkeypatch.setattr(mod, "FLOORS", dict.fromkeys(mod.FLOORS, 1))


def test_error_copy_lane_passes_on_real_tree() -> None:
    """The live tree reconciles (the 2026-06-10 audit's 3 doc drifts are fixed)
    and every parser is reading a populated source, not an empty husk."""
    mod = _load()
    assert len(mod._backend_error_table()) >= 80
    assert len(mod._strings_xml_error_entries()) >= 43
    assert len(mod._uitext_arms()) >= 40
    assert len(mod._repo_arms()) >= 35
    assert len(mod._doc_sections()) >= 25
    assert mod.main() == 0


def test_error_copy_lane_bites_on_each_surface(tmp_path: Path, monkeypatch, capsys) -> None:
    """Bite check: a cross-wired arm, a drifted doc 用户文案 and a ghost doc
    section must each FAIL the lane by name; the sister consistent fixture
    passes, proving the failures came from the injections."""
    mod = _load()
    cross_wired = _UITEXT_KT.replace('"alpha" -> R.string.error_alpha', '"alpha" -> R.string.error_beta')
    drifted_doc = _MAPPING_MD.replace("| 用户文案 | 甲安卓文案。 |", "| 用户文案 | 甲漂移文案。 |") + (
        "\n### ghost_code\n\n"
        "| 字段 | 内容 |\n"
        "|:---|:---|\n"
        "| 用户文案 | 幽灵文案。 |\n"
    )
    _install_fixture(mod, tmp_path / "broken", monkeypatch, uitext_kt=cross_wired, mapping_md=drifted_doc)
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert 'C2 ErrorUiText arm "alpha" -> R.string.error_beta is cross-wired' in out
    assert 'C9 doc 用户文案 for "alpha"' in out and "甲漂移文案" in out
    assert 'C8 doc section "ghost_code"' in out

    _install_fixture(mod, tmp_path / "ok", monkeypatch)
    assert mod.main() == 0


def test_error_copy_lane_ignores_commented_arms(tmp_path: Path, monkeypatch) -> None:
    """Comment-aware: a dead arm quoted in a // or /* */ comment must not enter
    the parsed tables (it would otherwise fail C1/C3 and C5 as a ghost code)."""
    mod = _load()
    commented_uitext = _UITEXT_KT.replace(
        "    else -> null\n",
        '    // dead arm kept for history: "zombie" -> R.string.error_zombie\n    else -> null\n',
    )
    commented_repo = _REPO_KT.replace(
        "        else -> serverMessage\n",
        '        /* "phantom" -> "幽灵文案。" */\n        else -> serverMessage\n',
    )
    _install_fixture(mod, tmp_path, monkeypatch, uitext_kt=commented_uitext, repo_kt=commented_repo)
    assert mod.main() == 0
