"""Project saved recognition evidence into the existing explicit review."""

import json
from datetime import date, datetime

from app.models import OcrFact
from app.schemas._recognition_time import RecognitionTimeCandidate, RecognitionTimeResponse
from app.services.currency_common import minor_amount_value

_ROLES = {
    "payment": "支付时间", "transaction": "交易时间", "consumption": "消费时间",
    "refund": "退款时间", "order": "下单时间", "created": "开票或创建时间",
    "printed": "打印时间", "captured": "截图或接收时间", "scheduled": "计划或到期时间",
    "unknown": "原件中的时间",
}
_REASONS = {
    "date_only": "原件只有日期，未补造时刻。",
    "year_inferred_from_capture_reference": "原件缺少年份；年份根据首次收录时间推定，请核对。",
    "date_inferred_from_capture_reference": "相对日期根据首次收录时间推定，请核对。",
    "reference_time_missing": "缺少完整日期，需对照原件填写。",
    "date_missing": "只有时刻，缺少发生日期。",
    "ambiguous_date_order": "日与月的顺序不明确，请选择原件实际表示的日期。",
    "ambiguous_timezone": "该地区当天有两个相同钟点，请在时间表单选择 UTC 偏移。",
    "nonexistent_local_time": "该时刻处在夏令时跳时区间，请核对时间与地区。",
    "invalid_timezone": "发生地时区无效，请核对。",
    "invalid_date": "日期无效，请对照原件填写。",
    "invalid_datetime": "时间或偏移无效，请对照原件填写。",
    "after_capture_date": "原件日期晚于首次收录日期，可能识别有误，请核对后填写。",
    "non_transaction_time": "这不是消费发生时间，保留供对照。",
}


def _candidate(item: dict, raw_text: str) -> RecognitionTimeCandidate:
    local = item.get("local_value") or ""
    precision = item.get("precision") or "unknown"
    reason = item.get("review_reason")
    role = item.get("role") or "unknown"
    try:
        date.fromisoformat(local) if precision == "date_only" else datetime.fromisoformat(local)
        valid = True
    except ValueError:
        valid = False
    original = "\n".join(raw_text[start:end] for start, end in item["raw_spans"])
    note = _REASONS.get(reason, "精确到秒。" if precision == "second" else "精确到分，原件未给出秒。")
    if item.get("timezone_basis") == "configured_timezone" and precision != "date_only":
        note += " 时区采用识别设置，请核对发生地区。"
    if item.get("timezone_basis") == "capture_timezone" and precision != "date_only":
        note += " 时区采用接收通知时的手机设置，请核对交易发生地区。"
    # Fixed offsets use the existing offset-only accounting command. An invented
    # IANA zone would change the printed clock or fail the kernel validation.
    zone = None if item.get("timezone_basis") == "printed_offset" else item.get("timezone_name")
    return RecognitionTimeCandidate(id=item["id"], label=_ROLES.get(role, _ROLES["unknown"]),
        explanation=note, original_text=original, local_value=local, precision=precision,
        source_timezone=zone, source_utc_offset_seconds=item.get("utc_offset_seconds"),
        can_apply=valid and role in {"payment", "transaction", "consumption", "unknown"}
        and reason not in {"invalid_date", "invalid_datetime", "nonexistent_local_time"})


def recognition_time(fact: OcrFact | None, *,
        notification: RecognitionTimeResponse | None = None) -> RecognitionTimeResponse | None:
    image = None
    if fact is not None and fact.evidence_json:
        evidence = json.loads(fact.evidence_json).get("field_parse")
        if evidence:
            image = project_time_evidence(fact.public_id, "image", evidence, fact.raw_text)
    # A print/order/capture clock cannot hide an actionable notification time.
    # Historical facts without field evidence still acquire no inferred precision.
    if image is not None and any(candidate.can_apply for candidate in image.candidates):
        return image
    return notification or image


def project_time_evidence(public_id: str, source: str, evidence: dict, raw_text: str) -> RecognitionTimeResponse | None:
    candidates = [_candidate(item, raw_text) for item in evidence["candidates"]
        if item["field"] == "expense_time"]
    if not candidates:
        return None
    decision = next(item for item in evidence["decisions"] if item["field"] == "expense_time")
    return RecognitionTimeResponse(evidence_public_id=public_id, source=source, parser_version=evidence["version"],
        status=decision["status"], candidates=candidates)


_AMOUNT_NOTES = {
    "transaction_not_completed": "原件显示支付尚未完成，请核实是否实际发生了这笔消费。",
    "repayment_receipt": "原件显示还款，请先核对交易类型；还款不应重复记成消费。",
    "refund_receipt": "原件显示退款，请核对类型与金额，不要当作新增消费。",
    "income_receipt": "原件显示收款或收入，请核对类型，不要当作消费。",
    "conflicting_transaction_kinds": "原件中出现了不同交易类型，请先核对。",
    "conflicting_transaction_amounts": "原件中的消费金额不一致，请对照原文填写。",
}
_AMOUNT_ROLES = {"payment": "支付金额", "expense": "支出", "total": "合计", "final_total": "结算合计", "rounded_total": "取整后合计", "order": "订单金额",
    "balance": "余额或额度", "discount": "优惠", "repayment": "还款", "refund": "退款",
    "income": "收入", "fee": "费用或找零", "unknown": "金额"}


def recognition_amount_notes(fact: OcrFact | None) -> list[str]:
    if fact is None or not fact.evidence_json:
        return []
    evidence = json.loads(fact.evidence_json).get("field_parse")
    if not evidence:
        return []
    decision = next((item for item in evidence["decisions"] if item["field"] == "amount_cents"), None)
    if decision is None or decision["status"] not in {"ambiguous", "needs_review"}:
        return []
    values = dict.fromkeys((item["value"], item["currency_code"], item.get("role"))
        for item in evidence["candidates"] if item["field"] == "amount_cents")
    return [_AMOUNT_NOTES.get(decision["reason"], "原件金额尚不能确定为消费金额，请核对现有草稿。"),
        *(f"{_AMOUNT_ROLES.get(role, '金额')}：{code} {minor_amount_value(value, code)}" for value, code, role in values)]
