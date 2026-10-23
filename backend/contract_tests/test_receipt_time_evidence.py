"""Counterexamples for transaction time, receipt provenance and safe OCR application."""

from datetime import UTC, datetime

import pytest

from app.models import Expense
from app.services.ocr_service import OcrResult, apply_ocr_result, ocr_fact_snapshot
from app.services.receipt_parse_service import parse_receipt_text


def parse(raw, **kwargs):
    kwargs.setdefault("timezone_name", "Asia/Shanghai")
    return parse_receipt_text(raw, currency_code="CNY", minor_unit_exponent=2, **kwargs)


def times(parsed):
    return [item for item in parsed.candidates if item.field == "expense_time"]


def decision(parsed):
    return next(item for item in parsed.decisions if item.field == "expense_time")


def test_page_month_heading_supplies_its_year_without_using_a_later_upload_year():
    raw = "2020年12月账单\n支付时间：12月31日23:59"
    result = parse(raw, reference_time=datetime(2026, 1, 1, tzinfo=UTC))
    candidate = times(result)[0]
    assert candidate.local_value == "2020-12-31T23:59"
    assert candidate.review_reason == "year_from_page_heading" and result.expense_time is None
    assert candidate.reference_time is None
    assert [raw[left:right] for left, right in candidate.raw_spans] == ["2020年12月账单", "支付时间：12月31日23:59"]


def test_month_heading_does_not_cross_into_another_month_or_borrow_a_date_below():
    for raw in ("2020年11月账单\n支付时间：12月31日23:59", "支付时间：12月31日23:59\n2020年12月账单"):
        candidate = times(parse(raw))[0]
        assert candidate.review_reason == "reference_time_missing"
        assert candidate.local_value == "12月31日23:59"


def test_page_heading_after_capture_preserves_the_conflict_and_both_sources():
    reference = datetime(2025, 12, 31, tzinfo=UTC)
    raw = "2026年12月账单\n支付时间：12月31日23:59"
    result = parse(raw, reference_time=reference)
    candidate = times(result)[0]
    assert candidate.local_value == "2026-12-31T23:59" and result.expense_time is None
    assert candidate.review_reason == "after_capture_date" and candidate.reference_time == reference.isoformat()
    assert raw[slice(*candidate.raw_spans[0])] == "2026年12月账单"


def test_page_year_heading_uses_the_dates_column_even_when_ocr_serializes_other_column_first():
    def block(text, left, top, right):
        return {"text": text, "box": [[left, top], [right, top], [right, top + 20], [left, top + 20]]}

    blocks = [block("2021年12月账单", 400, 10, 550), block("12月21日 09:20", 20, 70, 180),
        block("2020年12月账单", 20, 10, 180), block("12月22日 10:30", 400, 70, 560)]
    raw = "\n".join(row["text"] for row in blocks)
    candidates = times(parse(raw, evidence_blocks=blocks))
    assert {row.local_value for row in candidates} == {"2020-12-21T09:20", "2021-12-22T10:30"}
    for candidate in candidates:
        assert {blocks[index]["box"][0][0] for index in candidate.block_indices} in ({20}, {400})


def test_payment_time_is_separate_from_order_print_refund_and_capture_times():
    raw = "\n".join([
        "下单时间：2026-10-20 18:20", "支付时间：2026-10-21 10:20:31",
        "打印时间：2026-10-21 11:00", "退款时间：2026-10-22 12:30",
        "截图时间：2026-10-22 13:00",
    ])
    result = parse(raw)
    assert result.expense_time.isoformat() == "2026-10-21T02:20:31+00:00"
    assert {item.role for item in times(result)} == {"order", "payment", "printed", "refund", "captured"}
    for item in times(result):
        assert raw[slice(*item.raw_spans[0])].startswith(item.reasons[3].removeprefix("label:"))


@pytest.mark.parametrize("label", ["下单时间", "创建时间", "打印时间", "退款时间", "截图时间", "接收时间", "将于"])
def test_non_transaction_time_alone_cannot_fill_transaction_time(label):
    result = parse(f"{label}：2026-10-21 10:20\n交易金额：20.00")
    assert result.expense_time is None
    assert decision(result).reason == "non_transaction_time"


def test_conflicting_payment_times_abstain_even_with_more_precise_seconds():
    result = parse("支付时间：2026-10-21 10:20\n交易时间：2026-10-21 11:20:31")
    assert result.expense_time is None
    assert decision(result).status == "ambiguous"


def test_consistent_minute_and_second_evidence_can_refine_but_not_hide_conflicting_seconds():
    raw = "支付时间：2026-10-21 10:20\n交易时间：2026-10-21 10:20:31"
    result = parse(raw)
    assert result.expense_time.isoformat() == "2026-10-21T02:20:31+00:00"
    assert {item.precision for item in times(result)} == {"minute", "second"}
    conflict = parse(raw + "\n付款时间：2026-10-21 10:20:50")
    assert conflict.expense_time is None


def test_date_only_and_clock_only_do_not_invent_midnight_or_today():
    day = parse("交易日期：2018-06-13")
    assert day.expense_time is None
    assert times(day)[0].value == "2018-06-13"
    assert times(day)[0].precision == "date_only"
    assert decision(day).reason == "date_only"
    clock = parse("12:59\n交易时间：12:34")
    assert clock.expense_time is None
    assert len(times(clock)) == 1
    assert decision(clock).reason == "date_missing"


def test_year_inference_uses_frozen_reference_across_new_year_and_still_requires_review():
    reference = datetime(2025, 1, 1, 1, tzinfo=UTC)
    result = parse("交易时间：12月31日23:59", reference_time=reference)
    assert result.expense_time is None
    candidate = times(result)[0]
    assert candidate.local_value == "2024-12-31T23:59"
    assert candidate.inferred_components == ("year",)
    assert candidate.reference_time == reference.isoformat()
    assert decision(result).reason == "year_inferred_from_capture_reference"
    assert result == parse("交易时间：12月31日23:59", reference_time=reference)
    missing = parse("交易时间：12月31日23:59")
    assert missing.expense_time is None
    assert decision(missing).reason == "reference_time_missing"


@pytest.mark.parametrize(("raw", "zone", "reason"), [
    ("交易时间：2026-11-01 01:30", "America/New_York", "ambiguous_timezone"),
    ("交易时间：2026-03-08 02:30", "America/New_York", "nonexistent_local_time"),
    ("交易时间：2026-10-21 10:30", "Not/AZone", "invalid_timezone"),
    ("交易时间：2026-02-30 10:30", "Asia/Shanghai", "invalid_date"),
])
def test_invalid_or_ambiguous_wall_time_is_retained_without_an_invented_instant(raw, zone, reason):
    result = parse(raw, timezone_name=zone)
    assert result.expense_time is None
    assert decision(result).reason == reason
    assert times(result)[0].raw_spans == ((0, len(raw)),)


def test_printed_offset_dominates_device_timezone_and_resolves_dst_fold():
    result = parse("付款时间：2026-11-01 01:30-05:00", timezone_name="America/New_York")
    assert result.expense_time.isoformat() == "2026-11-01T06:30:00+00:00"
    candidate = times(result)[0]
    assert candidate.precision == "minute"
    assert candidate.timezone_basis == "printed_offset"
    assert candidate.utc_offset_seconds == -18000


@pytest.mark.parametrize("suffix", ["+08:5", "+08:600", "+15:00", "GMT+wrong", " CST"])
def test_malformed_or_ambiguous_printed_timezone_cannot_fall_back_to_configured_zone(suffix):
    result = parse("交易时间：2026-10-21 10:30" + suffix)
    assert result.expense_time is None
    assert decision(result).reason == "invalid_datetime"
    raw = "交易时间：2026-10-21 10:30" + suffix
    assert raw[slice(*times(result)[0].raw_spans[0])] == raw


@pytest.mark.parametrize("raw", ["交易时间：0001-01-01 00:00+14:00", "交易时间：9999-12-31 23:59-14:00",
    "交易时间：2026-01-01 晚上12:30", "交易时间：2026-01-01 上午12:30"])
def test_unrepresentable_instant_or_ambiguous_midnight_never_becomes_a_fact(raw):
    result = parse(raw)
    assert result.expense_time is None
    assert decision(result).reason == "invalid_datetime"


def test_numeric_date_order_remains_ambiguous_without_a_format_contract():
    result = parse("交易时间：03/04/2026 13:20")
    assert result.expense_time is None
    assert {item.local_value for item in times(result)} == {"2026-03-04T13:20", "2026-04-03T13:20"}
    clear = parse("交易时间：13/04/2026 1:20 PM")
    assert clear.expense_time.isoformat() == "2026-04-13T05:20:00+00:00"


@pytest.mark.parametrize("literal", ["2518-03-12", "2518-03-12 13:07"])
def test_ocr_future_date_is_reviewed_against_frozen_capture_instead_of_auto_filled(literal):
    reference = datetime(2026, 10, 22, tzinfo=UTC)
    raw = f"交易时间：{literal}"
    result = parse(raw, reference_time=reference)
    assert result.expense_time is None
    assert decision(result).reason == "after_capture_date"
    assert times(result)[0].local_value == literal.replace(" ", "T")
    assert times(result)[0].reference_time == reference.isoformat()


def test_full_month_date_and_numeric_date_cannot_hide_a_conflicting_year():
    result = parse("04:54 pm, 27 March, 2018\n27/03/2016 16:54:04")
    assert result.expense_time is None
    assert decision(result).status == "ambiguous"
    assert {item.local_value for item in times(result)} == {"2018-03-27", "2016-03-27T16:54:04"}


def test_time_provenance_joins_only_adjacent_original_blocks_and_preserves_crlf_offsets():
    blocks = [{"text": value} for value in ("小票", "支付时间", "2026-10-21", "10:20:31")]
    raw = "\n".join(item["text"] for item in blocks)
    result = parse(raw, evidence_blocks=blocks)
    candidate = times(result)[0]
    assert candidate.block_indices == (1, 2, 3)
    assert raw[slice(*candidate.raw_spans[0])] == "支付时间\n2026-10-21\n10:20:31"
    spaced = " 小票 \r\n\r\n 支付时间 \r\n 2026-10-21 \r\n 10:20:31 "
    value = times(parse(spaced))[0]
    assert spaced[slice(*value.raw_spans[0])] == "支付时间 \r\n 2026-10-21 \r\n 10:20:31"


def test_provider_guess_cannot_bypass_time_conflict_and_fact_keeps_original_evidence():
    raw = "支付时间：2026-10-21 10:20\n交易时间：2026-10-21 11:20"
    evidence = {"blocks": [{"text": line} for line in raw.splitlines()], "recipe": "original"}
    supplied = datetime(2026, 10, 21, 2, 20, tzinfo=UTC)
    result = OcrResult(raw_text=raw, confidence=.99, expense_time=supplied, evidence=evidence)
    expense = Expense(status="pending", home_currency_code="CNY", original_currency_code="CNY",
        created_at=datetime(2026, 10, 22, tzinfo=UTC), category="其他")
    apply_ocr_result(expense, result, timezone_name="Asia/Shanghai")
    assert expense.expense_time is None
    snapshot = ocr_fact_snapshot(result, expense=expense, timezone_name="Asia/Shanghai")
    assert snapshot.parsed_expense_time is None
    assert snapshot.evidence["blocks"] == evidence["blocks"]
    assert snapshot.evidence["recipe"] == "original"
    assert len([item for item in snapshot.evidence["field_parse"]["candidates"] if item["field"] == "expense_time"]) == 2
    expense.expense_time = supplied
    expense.time_precision = "instant"
    apply_ocr_result(expense, result, timezone_name="Asia/Shanghai")
    assert expense.expense_time == supplied  # Human-owned draft time is preserved.
