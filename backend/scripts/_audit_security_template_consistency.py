"""Audit single-source security templates across provider-style modules.

This lane is intentionally small and concrete. It guards drift patterns that
have already caused findings in this repository:

* budget-advisor live provider names must come from one module;
* OCR/advisor category lists must use ``DEFAULT_CATEGORIES`` rather than a
  copied prompt literal;
* live outbound providers must keep base-url and category-output validators.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _function_contains(source: str, name: str, needles: tuple[str, ...]) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node) or ""
            return all(needle in segment for needle in needles)
    return False


def main() -> int:
    failures: list[str] = []

    provider_names = _read("app/services/budget_advisor_service/_provider_names.py")
    advisor_providers = _read("app/services/budget_advisor_service/_providers.py")
    advisor_audit = _read("app/services/budget_advisor_service/_audit.py")
    ocr_providers = _read("app/services/ocr_service/_providers.py")
    ocr_llm_parsing = _read("app/services/ocr_service/_llm_parsing.py")

    if "LIVE_PROVIDER_NAMES = OPENAI_COMPAT_PROVIDER_NAMES" not in provider_names:
        failures.append("budget advisor live provider names are not derived from provider_names.py")
    if "from app.services.budget_advisor_service._provider_names import" not in advisor_audit:
        failures.append("budget advisor audit no longer imports provider names from the single source")
    if "OPENAI_COMPAT_PROVIDER_NAMES" not in advisor_providers:
        failures.append("budget advisor provider factory no longer uses OPENAI_COMPAT_PROVIDER_NAMES")

    if '"/".join(DEFAULT_CATEGORIES)' not in advisor_providers:
        failures.append("budget advisor prompt no longer derives categories from DEFAULT_CATEGORIES")
    if '"餐饮/交通/购物"' in ocr_providers or "category(string|null, 餐饮/" in ocr_providers:
        failures.append("OCR local-LLM prompt contains a copied category list instead of DEFAULT_CATEGORIES")
    if '"/".join(DEFAULT_CATEGORIES)' not in ocr_providers:
        failures.append("OCR local-LLM prompt no longer derives categories from DEFAULT_CATEGORIES")
    category_guard_ok = _function_contains(
        ocr_llm_parsing,
        "_coerce_category",
        ("normalize_category", "DEFAULT_CATEGORIES", "normalized in DEFAULT_CATEGORIES"),
    )
    if not category_guard_ok:
        failures.append("OCR local-LLM parser no longer drops categories outside DEFAULT_CATEGORIES")
    if "_validate_base_url(settings.budget_advisor_base_url)" not in advisor_providers:
        failures.append("budget advisor live base_url no longer passes through _validate_base_url")

    if failures:
        print("FAIL: security template / single-source drift:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("OK: provider security templates remain single-source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
