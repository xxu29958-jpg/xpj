"""Evaluate frozen inputs through the real OCR provider and fact parsing path.

Input context lives in input.json; annotation values are read only by the scorer.
Every requested provider/sample counts as attempted, including dependency errors.
The mock runner is an explicitly synthetic text-parser diagnostic, not OCR evidence.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.models import Expense  # noqa: E402
from app.services.ocr_service import OcrResult, ocr_fact_snapshot  # noqa: E402
from app.services.ocr_service._providers import LocalLlmOcrProvider, RapidOcrProvider  # noqa: E402
from app.services.original_read_service import OriginalSnapshot, _copy_original  # noqa: E402
from scripts.ocr_benchmark_data import FIELDS, BenchmarkInput, discover_fixtures  # noqa: E402
from scripts.ocr_benchmark_metrics import BenchmarkReport, ScoreRow, score  # noqa: E402

DEFAULT_FIXTURE_DIR = _BACKEND_ROOT / "tests" / "_infra" / "ocr_fixtures"


def _run_empty(inputs: BenchmarkInput) -> OcrResult:
    return OcrResult(raw_text="", confidence=None)


def _run_mock(inputs: BenchmarkInput) -> OcrResult:
    if inputs.raw_text is None:
        raise ValueError("mock requires explicit input.raw_text; annotations are never OCR input")
    return OcrResult(raw_text=inputs.raw_text, confidence=None)


def _run_image(inputs: BenchmarkInput, provider: RapidOcrProvider | LocalLlmOcrProvider) -> OcrResult:
    if inputs.image is None:
        raise ValueError("image provider requires an image")
    with ExitStack() as cleanup:
        directory = cleanup.enter_context(TemporaryDirectory(prefix="ticketbox-benchmark-"))
        path = Path(directory) / f"original{inputs.image.suffix}"
        digest, size, modified_at = _copy_original(inputs.image, path)
        if digest != inputs.image_sha256:
            raise ValueError("image changed after dataset discovery")
        original = OriginalSnapshot(path=path, media_type=mimetypes.guess_type(path.name)[0] or "image/jpeg",
                                    sha256=digest, size_bytes=size, verified=True,
                                    source_modified_at=modified_at, _cleanup=cleanup)
        return provider.extract_snapshot(original, timezone_name=inputs.timezone_name)


def _run_rapidocr(inputs: BenchmarkInput) -> OcrResult:
    return _run_image(inputs, RapidOcrProvider())


def _run_local_llm(inputs: BenchmarkInput) -> OcrResult:
    return _run_image(inputs, LocalLlmOcrProvider())


_PROVIDER_RUNNERS = {"empty": _run_empty, "mock": _run_mock,
                     "rapidocr": _run_rapidocr, "local_llm": _run_local_llm}


def _prediction(result: OcrResult, inputs: BenchmarkInput) -> tuple[dict, dict]:
    # Same frozen currency context and parser as append-only OcrFact. No GT fields.
    expense = Expense(status="pending", original_currency_code=inputs.currency_code,
                      home_currency_code=inputs.currency_code)
    fact = ocr_fact_snapshot(result, expense=expense, timezone_name=inputs.timezone_name)
    instant = fact.parsed_expense_time
    return {"amount": {"minor": fact.parsed_amount_cents, "currency": inputs.currency_code}
            if fact.parsed_amount_cents is not None else None,
            "merchant": fact.parsed_merchant, "category": fact.parsed_category,
            # Current provider contract emits instants only; date-only GT cannot
            # be awarded a match by truncating that instant to a calendar date.
            "time": {"value": instant.isoformat(), "precision": "instant"} if instant else None}, fact.evidence["field_parse"]


def benchmark(fixture_dir: Path, providers: list[str], *, split: str | None = None) -> BenchmarkReport:
    from scripts.ocr_benchmark_stages import analyze_fields

    if not providers or len(providers) != len(set(providers)):
        raise ValueError("specify at least one provider, without duplicates")
    unknown = set(providers).difference(_PROVIDER_RUNNERS)
    if unknown:
        raise ValueError(f"unknown providers: {', '.join(sorted(unknown))}")
    fixtures = discover_fixtures(fixture_dir, split=split)
    report = BenchmarkReport(manifest=[fixture.identity for fixture in fixtures])
    for fixture in fixtures:
        for provider in providers:
            start = time.monotonic()
            prediction, error, outcome = {}, None, "success"
            raw_text, field_parse = "", {}
            try:
                result = _PROVIDER_RUNNERS[provider](fixture.inputs)
                raw_text = result.raw_text or ""
                prediction, field_parse = _prediction(result, fixture.inputs)
            except Exception as exc:  # noqa: BLE001 — record every failure and continue the finite sample list
                outcome, error = "error", f"{type(exc).__name__}: {exc}"
            elapsed_ms = (time.monotonic() - start) * 1000
            report.rows.append(ScoreRow(
                fixture=fixture.name, group_id=fixture.group_id, source_kind=fixture.source_kind,
                split=fixture.split, provider=provider, outcome=outcome, elapsed_ms=elapsed_ms,
                prediction=prediction, scores=score(prediction, fixture.labels, failed=outcome != "success"),
                labels={name: fixture.labels[name].state for name in FIELDS}, error=error,
                app_tag=fixture.app_tag,
                field_analysis=analyze_fields(raw_text, field_parse, prediction, fixture.labels,
                                             timezone_name=fixture.inputs.timezone_name, failed=outcome != "success"),
            ))
    return report


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--providers", default="rapidocr", help="Explicit comma-separated providers; all are required.")
    parser.add_argument("--split", choices=("development", "holdout", "diagnostic"),
                        help="Select by input metadata before opening annotations; W0 uses development only.")
    parser.add_argument("--json-output", type=Path, help="Save frozen identities, outcomes, timings and denominators.")
    args = parser.parse_args(argv)
    try:
        report = benchmark(args.fixture_dir, [value.strip() for value in args.providers.split(",") if value.strip()],
                           split=args.split)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Invalid benchmark input: {exc}", file=sys.stderr)
        return 2
    print(report.to_markdown())
    print(report.aggregate_per_provider())
    if args.json_output:
        args.json_output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
