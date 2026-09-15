"""Classify PR file lists onto capability IDs. Heuristic by path; leftover = UNMAPPED."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "file-attribution.tsv"

RULES: list[tuple[str, tuple[str, ...]]] = [
    ("docs/architecture/openapi_contract.json", ("GENERATED", "A12")),
    ("docs/", ("DOCS", "SHARED")),
    (".github/", ("C02", "CI")),
    ("android/app/src/main/java/com/ticketbox/ui/screens/recurring/RecurringEditor", ("B01", "B02", "B06")),
    ("android/app/src/test/java/com/ticketbox/ui/screens/RecurringCapturedCurrency", ("B01", "B02")),
    ("android/app/src/androidTest/java/com/ticketbox/ui/screens/RecurringEditorRestoration", ("B01", "B06")),
    ("backend/app/templates/web/recurring.html", ("B01", "B02", "B03")),
    ("backend/app/routes/web_recurring.py", ("B01", "B02")),
    ("backend/tests/test_web_recurring_form_continuity.py", ("B01", "B02")),
    ("RecurringPaymentJourney", ("B01", "B04", "B06", "B08", "B10", "C01")),
    ("RecurringPeriodPayment", ("B04", "B06", "B07", "B08", "B13")),
    ("RecurringOccurrence", ("B03", "B04", "B07", "B10", "B11")),
    ("web_recurring_occurrences", ("B04", "B10", "B11")),
    ("recurring_occurrence.html", ("B04", "B10", "B11")),
    ("test_web_period_payment", ("B09", "B10", "B11", "C01")),
    ("_web_expense_return_context", ("B10", "B12")),
    ("web_expense_create.py", ("B04", "B05", "B09", "B12")),
    ("expense_new.html", ("B04", "B05")),
    ("manual-draft", ("B05",)),
    ("manual-entry.js", ("B05",)),
    ("ExpenseManualCreation", ("B07", "B08")),
    ("ExpenseLedgerRepositoryActions", ("B07", "B08", "B09")),
    ("LedgerManualExpenseSheet", ("B04", "B06", "B07")),
    ("pending_fx", ("A02", "A04", "A05", "A06")),
    ("PendingFx", ("A02", "A04", "A05")),
    ("foreign_bill", ("A01", "A02", "A06")),
    ("ForeignBill", ("A01", "A02")),
    ("exchange_rate", ("A02", "A03")),
    ("ExchangeRate", ("A02", "A03")),
    ("ManualExchange", ("A03",)),
    ("background_task", ("A04", "A05")),
    ("BackgroundTask", ("A04", "A05")),
    ("PendingMutation", ("A07", "A08", "A09")),
    ("Outbox", ("A08", "A09")),
    ("ExpenseAcceptance", ("A08", "A09")),
    ("PendingViewModel", ("A09", "A10")),
    ("PendingUiState", ("A09", "A10")),
    ("web_expense_lifecycle", ("A10", "B12")),
    ("Reject", ("A10",)),
    ("UndoExpense", ("A10",)),
    ("ExpenseEdit", ("A03", "A06", "A09")),
    ("pending/", ("A07", "A09", "A11")),
    ("PendingExpense", ("A07", "A08", "A09")),
    ("csv", ("A01",)),
    ("Csv", ("A01",)),
    ("ocr", ("A01",)),
    ("Ocr", ("A01",)),
    ("notification", ("A01",)),
    ("Notification", ("A01",)),
    ("upload", ("A01",)),
    ("Upload", ("A01",)),
    ("data_quality", ("A11",)),
    ("DataQuality", ("A11",)),
    ("money_contract", ("A12",)),
    ("canonical_money", ("A12",)),
    ("currency_binding", ("A12",)),
    ("debt", ("A12",)),
    ("Debt", ("A12",)),
    ("offset", ("A12", "B12")),
    ("Offset", ("A12", "B12")),
    ("refund", ("A12",)),
    ("projection", ("A12", "B03")),
    ("Budget", ("A12", "B03")),
    ("income_plan", ("A12",)),
    ("IncomePlan", ("A12",)),
    ("CreateExpense", ("A08", "B08", "B09")),
    ("ConfirmExpense", ("A06", "A09")),
    ("web_budget_fx", ("A12", "B12")),
    ("LedgerRequestGuard", ("B07", "A09")),
    ("ExpenseRepositoryCore", ("A08", "B08")),
]


def classify(path: str) -> tuple[str, ...]:
    path = path.lstrip("\ufeff")
    hits: list[str] = []
    for needle, caps in RULES:
        if needle in path or path.startswith(needle.rstrip("/")):
            for cap in caps:
                if cap not in hits:
                    hits.append(cap)
    if hits:
        return tuple(hits)
    lower = path.lower()
    if "recurring" in lower:
        return ("B03", "SHARED")
    if "pending" in lower or "/fx" in lower or "exchange" in lower:
        return ("A04", "SHARED")
    prefixes = (
        ("android/app/src/main/java/com/ticketbox/data/local/", ("A07", "A08")),
        ("android/app/src/main/java/com/ticketbox/data/remote/", ("A12", "SHARED")),
        ("android/app/src/main/java/com/ticketbox/data/repository/", ("A08", "A09", "SHARED")),
        ("android/app/src/main/java/com/ticketbox/domain/", ("A12", "SHARED")),
        ("android/app/src/main/java/com/ticketbox/ui/navigation/", ("A09", "B12", "SHARED")),
        ("android/app/src/main/java/com/ticketbox/ui/screens/expense/", ("A03", "A06", "A09")),
        ("android/app/src/main/java/com/ticketbox/ui/screens/pending/", ("A09", "A10", "A11")),
        ("android/app/src/main/java/com/ticketbox/ui/", ("A11", "SHARED")),
        ("android/app/src/main/java/com/ticketbox/viewmodel/", ("A09", "A10", "SHARED")),
        ("android/app/src/main/java/com/ticketbox/", ("SHARED", "DI")),
        ("android/app/src/test/", ("TEST", "SHARED")),
        ("android/app/src/androidTest/", ("TEST", "SHARED")),
        ("android/app/src/main/res/", ("SHARED", "UI")),
        ("backend/app/services/", ("A04", "A06", "SHARED")),
        ("backend/app/routes/", ("A09", "B12", "SHARED")),
        ("backend/app/schemas/", ("A12",)),
        ("backend/app/templates/", ("A11", "SHARED")),
        ("backend/app/static/", ("B05", "A11", "SHARED")),
        ("backend/tests/", ("TEST", "SHARED")),
        ("backend/migrations/", ("A12",)),
        ("backend/app/", ("A12", "SHARED")),
        ("docs/", ("DOCS", "SHARED")),
        (".github/", ("C02", "CI")),
        ("backend/scripts/", ("A09", "A12", "SHARED")),
        ("scripts/", ("C02", "OUT_OF_SCOPE")),
        ("distribution/", ("C02", "OUT_OF_SCOPE")),
        ("desktop/", ("C02", "OUT_OF_SCOPE")),
    )
    for prefix, caps in prefixes:
        if path.startswith(prefix):
            return caps
    return ("UNMAPPED",)


def load_tsv(name: str) -> list[tuple[str, str]]:
    rows = []
    p = ROOT / name
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        path = parts[0].lstrip("\ufeff")
        status = parts[1] if len(parts) > 1 else ""
        rows.append((path, status))
    return rows


def main() -> None:
    sources = {
        "404": load_tsv("pr-404-files.tsv"),
        "405": load_tsv("pr-405-files.tsv"),
        "409": load_tsv("pr-409-files.tsv"),
        "412": load_tsv("pr-412-files.tsv"),
        "413": load_tsv("pr-413-files.tsv"),
        "414": load_tsv("pr-414-files.tsv"),
        "415": load_tsv("pr-415-files.tsv"),
    }
    paths_404 = {p for p, _ in sources["404"]}
    out_rows = []
    unmapped = []
    for pr, files in sources.items():
        for path, status in files:
            caps = classify(path)
            shared = "Y" if pr == "405" and path in paths_404 else "N"
            if caps == ("UNMAPPED",):
                unmapped.append((pr, path))
            out_rows.append({
                "pr": pr,
                "path": path,
                "diff_status": status,
                "capabilities": ",".join(caps),
                "overlap_404": shared,
            })
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pr", "path", "diff_status", "capabilities", "overlap_404"], delimiter="\t")
        w.writeheader()
        w.writerows(out_rows)
    summary = {
        "rows": len(out_rows),
        "unmapped": len(unmapped),
        "unmapped_samples": unmapped[:40],
        "by_pr": {pr: len(files) for pr, files in sources.items()},
    }
    (ROOT / "file-attribution-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
