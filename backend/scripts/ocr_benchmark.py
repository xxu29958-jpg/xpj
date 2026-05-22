"""OCR provider benchmark harness — PR-6.

Compares every configured OCR provider on the same fixture set and emits
a markdown report. Used to make a data-driven choice between RapidOCR /
PaddleOCR / local_llm before committing PR-7 (OCR enhancement) or PR-8
(line-item extraction).

Fixture layout (anything under ``--fixture-dir`` matching this shape):

    fixtures/
      receipt_01/
        image.png          # the raw receipt screenshot
        ground_truth.json  # {amount_cents, merchant, expense_time, category}
      receipt_02/
        image.jpg
        ground_truth.json
      ...

Run (Windows PowerShell, paste-friendly forward slashes):

    backend/.venv/Scripts/python.exe backend/scripts/ocr_benchmark.py \
        --fixture-dir backend/tests/_infra/ocr_fixtures \
        --providers empty,mock,rapidocr,local_llm

Provider availability:

- ``empty`` always works (returns nothing -> 0% on every metric, sanity floor)
- ``mock`` always works (hard-coded raw_text, sanity ceiling for the parse layer)
- ``rapidocr`` requires ``backend/requirements-ocr.txt`` installed
- ``local_llm`` requires ``LOCAL_LLM_BASE_URL`` to be a reachable loopback URL

Failing providers are reported as ``SKIP`` rather than crashing the run.

Real receipt fixtures are NOT in the repo (would leak personal data). The
fixture directory ships with one synthetic ground-truth file the harness
itself can use to smoke-test the runner. Drop your own PNG/JPG + ground
truth pairs into the same directory to evaluate real receipts.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# When invoked from repo root the script is at ``backend/scripts/...``;
# add backend/ to sys.path so ``app.*`` imports work without going through
# backend/run.bat.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.ocr_service import OcrResult  # noqa: E402
from app.services.receipt_parse_service import parse_receipt_text  # noqa: E402

DEFAULT_FIXTURE_DIR = _BACKEND_ROOT / "tests" / "_infra" / "ocr_fixtures"
DEFAULT_TIMEZONE = "Asia/Shanghai"


@dataclass
class GroundTruth:
    amount_cents: int | None = None
    merchant: str | None = None
    expense_time: str | None = None  # ISO 8601
    category: str | None = None
    raw_text: str | None = None  # optional: when image-less, lets ``mock`` parse it directly

    @classmethod
    def from_json(cls, path: Path) -> GroundTruth:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            amount_cents=data.get("amount_cents"),
            merchant=data.get("merchant"),
            expense_time=data.get("expense_time"),
            category=data.get("category"),
            raw_text=data.get("raw_text"),
        )


@dataclass
class ProviderRun:
    provider: str
    fixture: str
    available: bool
    elapsed_ms: int
    result: OcrResult | None
    error: str | None = None


@dataclass
class ScoreRow:
    fixture: str
    provider: str
    amount_match: bool | None
    merchant_match: bool | None
    time_match: bool | None
    category_match: bool | None
    elapsed_ms: int
    note: str = ""

    def metrics(self) -> list[str]:
        def cell(v: bool | None) -> str:
            if v is None:
                return "—"
            return "✓" if v else "✗"

        return [cell(self.amount_match), cell(self.merchant_match), cell(self.time_match), cell(self.category_match)]


@dataclass
class BenchmarkReport:
    rows: list[ScoreRow] = field(default_factory=list)

    def add(self, row: ScoreRow) -> None:
        self.rows.append(row)

    def to_markdown(self) -> str:
        if not self.rows:
            return "_no fixtures evaluated_\n"
        lines = [
            "| Fixture | Provider | Amount | Merchant | Time | Category | Latency | Note |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in self.rows:
            metrics = row.metrics()
            lines.append(
                f"| {row.fixture} | {row.provider} | {metrics[0]} | {metrics[1]} | "
                f"{metrics[2]} | {metrics[3]} | {row.elapsed_ms}ms | {row.note} |"
            )
        return "\n".join(lines) + "\n"

    def aggregate_per_provider(self) -> str:
        per: dict[str, dict[str, int]] = {}
        for row in self.rows:
            bucket = per.setdefault(row.provider, {"runs": 0, "amount": 0, "merchant": 0, "time": 0, "category": 0, "elapsed_ms": 0})
            bucket["runs"] += 1
            bucket["elapsed_ms"] += row.elapsed_ms
            for key, value in (("amount", row.amount_match), ("merchant", row.merchant_match),
                               ("time", row.time_match), ("category", row.category_match)):
                if value:
                    bucket[key] += 1
        if not per:
            return ""
        lines = [
            "",
            "| Provider | Runs | Amount % | Merchant % | Time % | Category % | Avg Latency |",
            "|---|---|---|---|---|---|---|",
        ]
        for provider, b in sorted(per.items()):
            runs = b["runs"] or 1
            lines.append(
                f"| {provider} | {b['runs']} | "
                f"{100 * b['amount'] // runs}% | "
                f"{100 * b['merchant'] // runs}% | "
                f"{100 * b['time'] // runs}% | "
                f"{100 * b['category'] // runs}% | "
                f"{b['elapsed_ms'] // runs}ms |"
            )
        return "\n".join(lines) + "\n"


def _discover_fixtures(fixture_dir: Path) -> list[tuple[str, Path | None, GroundTruth]]:
    """Return list of (name, image_path_or_None, ground_truth).

    A fixture is any subdirectory of ``fixture_dir`` containing
    ``ground_truth.json``. The image file (image.png / image.jpg / image.webp)
    is optional — fixtures without an image still let the mock/empty
    provider exercise the parse layer using ``raw_text`` from the ground
    truth.
    """
    fixtures: list[tuple[str, Path | None, GroundTruth]] = []
    if not fixture_dir.is_dir():
        return fixtures
    for entry in sorted(fixture_dir.iterdir()):
        if not entry.is_dir():
            continue
        gt_path = entry / "ground_truth.json"
        if not gt_path.is_file():
            continue
        gt = GroundTruth.from_json(gt_path)
        image: Path | None = None
        for candidate in ("image.png", "image.jpg", "image.jpeg", "image.webp"):
            p = entry / candidate
            if p.is_file():
                image = p
                break
        fixtures.append((entry.name, image, gt))
    return fixtures


def _run_empty(image: Path | None, gt: GroundTruth, timezone_name: str) -> OcrResult:
    return OcrResult(raw_text="", confidence=None)


def _run_mock(image: Path | None, gt: GroundTruth, timezone_name: str) -> OcrResult:
    # The mock provider's job is to exercise the *parse* layer; we feed it
    # the ground-truth raw_text when present, otherwise a canned bank-style
    # message that the parser knows how to handle.
    raw_text = gt.raw_text or (
        "中国建设银行\n交易提醒\n交易时间：2026年5月4日 16:23:25\n交易金额：18.51（人民币）"
    )
    parsed = parse_receipt_text(raw_text, timezone_name=timezone_name)
    return OcrResult(
        raw_text=raw_text,
        confidence=parsed.confidence,
        amount_cents=parsed.amount_cents,
        merchant=parsed.merchant,
        expense_time=parsed.expense_time,
        category=parsed.category,
    )


def _run_rapidocr(image: Path | None, gt: GroundTruth, timezone_name: str) -> OcrResult:
    if image is None:
        raise RuntimeError("rapidocr requires an image; fixture has none")
    try:
        from rapidocr import RapidOCR  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("rapidocr not installed (backend/requirements-ocr.txt)") from exc
    result = RapidOCR()(str(image))
    texts = [text.strip() for text in (result.txts or ()) if text and text.strip()]
    raw_text = "\n".join(texts)
    scores = [float(s) for s in (result.scores or ()) if s is not None]
    confidence = (sum(scores) / len(scores)) if scores else None
    parsed = parse_receipt_text(raw_text, timezone_name=timezone_name)
    return OcrResult(
        raw_text=raw_text,
        confidence=confidence if confidence is not None else parsed.confidence,
        amount_cents=parsed.amount_cents,
        merchant=parsed.merchant,
        expense_time=parsed.expense_time,
        category=parsed.category,
    )


def _run_local_llm(image: Path | None, gt: GroundTruth, timezone_name: str) -> OcrResult:
    # Reaching into the real LocalLlmOcrProvider is awkward (it wants an
    # Expense ORM row); harness invokes the underlying HTTP call directly.
    if image is None:
        raise RuntimeError("local_llm requires an image; fixture has none")
    raise RuntimeError(
        "local_llm benchmark needs a fakeable LLM endpoint — see TODO in this script. "
        "Wire it once a real LLM is configured."
    )


_PROVIDER_RUNNERS = {
    "empty": _run_empty,
    "mock": _run_mock,
    "rapidocr": _run_rapidocr,
    "local_llm": _run_local_llm,
}


def _score(result: OcrResult, gt: GroundTruth) -> dict[str, bool | None]:
    def amount() -> bool | None:
        if gt.amount_cents is None and result.amount_cents is None:
            return None
        return gt.amount_cents == result.amount_cents

    def merchant() -> bool | None:
        if not gt.merchant and not result.merchant:
            return None
        if not gt.merchant or not result.merchant:
            return False
        g, r = gt.merchant.lower(), result.merchant.lower()
        return g in r or r in g

    def time_match() -> bool | None:
        if gt.expense_time is None and result.expense_time is None:
            return None
        if gt.expense_time is None or result.expense_time is None:
            return False
        try:
            g = datetime.fromisoformat(gt.expense_time.replace("Z", "+00:00")).date()
        except ValueError:
            return False
        r_dt = result.expense_time
        r = r_dt.date() if isinstance(r_dt, datetime) else (r_dt if isinstance(r_dt, date) else None)
        if r is None:
            return False
        return g == r

    def category() -> bool | None:
        if not gt.category and not result.category:
            return None
        if not gt.category or not result.category:
            return False
        return gt.category == result.category

    return {
        "amount": amount(),
        "merchant": merchant(),
        "time": time_match(),
        "category": category(),
    }


def benchmark(fixture_dir: Path, providers: list[str], timezone_name: str) -> BenchmarkReport:
    fixtures = _discover_fixtures(fixture_dir)
    report = BenchmarkReport()
    if not fixtures:
        return report
    for fixture_name, image, gt in fixtures:
        for provider in providers:
            runner = _PROVIDER_RUNNERS.get(provider)
            if runner is None:
                report.add(ScoreRow(
                    fixture=fixture_name, provider=provider,
                    amount_match=None, merchant_match=None, time_match=None, category_match=None,
                    elapsed_ms=0, note="unknown provider",
                ))
                continue
            start = time.monotonic()
            try:
                result = runner(image, gt, timezone_name)
                elapsed_ms = int((time.monotonic() - start) * 1000)
                scores = _score(result, gt)
                report.add(ScoreRow(
                    fixture=fixture_name, provider=provider,
                    amount_match=scores["amount"], merchant_match=scores["merchant"],
                    time_match=scores["time"], category_match=scores["category"],
                    elapsed_ms=elapsed_ms,
                ))
            except Exception as exc:  # noqa: BLE001 — harness must stay alive
                elapsed_ms = int((time.monotonic() - start) * 1000)
                report.add(ScoreRow(
                    fixture=fixture_name, provider=provider,
                    amount_match=None, merchant_match=None, time_match=None, category_match=None,
                    elapsed_ms=elapsed_ms, note=f"SKIP: {type(exc).__name__}: {exc}",
                ))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OCR provider benchmark harness.")
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=DEFAULT_FIXTURE_DIR,
        help="Directory containing fixture subdirs with ground_truth.json + optional image.{png,jpg}",
    )
    parser.add_argument(
        "--providers",
        default="empty,mock,rapidocr,local_llm",
        help="Comma-separated provider names to benchmark (in order).",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"Default timezone for parsing (default: {DEFAULT_TIMEZONE}).",
    )
    args = parser.parse_args(argv)

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    report = benchmark(args.fixture_dir, providers, args.timezone)

    print(f"# OCR Benchmark Report\n\nFixture dir: `{args.fixture_dir}`\n")
    print(report.to_markdown())
    print(report.aggregate_per_provider())
    if not report.rows:
        print("_no fixtures found — drop `<name>/ground_truth.json` (+ optional `image.png`) into the fixture dir_")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
