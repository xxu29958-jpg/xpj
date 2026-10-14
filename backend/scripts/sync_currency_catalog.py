"""Update Android's offline currency metadata from the shared money catalog."""

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/app/currency_catalog.py"
TARGET = ROOT / "android/app/src/main/java/com/ticketbox/domain/model/CurrencyCode.kt"


def render(source: str) -> str:
    assignment = next(node for node in ast.parse(SOURCE.read_text(encoding="utf-8")).body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "CURRENCY_CATALOG" for target in node.targets))
    catalog = ast.literal_eval(assignment.value)
    entries = "\n".join(f"    {code}({', '.join(json.dumps(value, ensure_ascii=False) for value in (code, *metadata))})"
        + (";" if index == len(catalog) - 1 else ",") for index, (code, metadata) in enumerate(catalog.items()))
    start, end = "    // BEGIN GENERATED CURRENCY CATALOG", "    // END GENERATED CURRENCY CATALOG"
    return source[:source.index(start)] + start + "\n" + entries + "\n" + source[source.index(end):]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    current = TARGET.read_text(encoding="utf-8")
    generated = render(current)
    if args.check:
        if generated != current:
            raise SystemExit("Currency metadata differs: run backend/scripts/sync_currency_catalog.py")
    else:
        TARGET.write_text(generated, encoding="utf-8")
