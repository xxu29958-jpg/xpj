"""债务账单解析 provider 管线（ADR-0049 §D 设计盘）。

不同于小票 OCR（``ocr_service``，解析目标=支出字段、图挂 Expense），债务账单的
解析目标是**还款条款**：平台/发卡方、欠款总额、分期期数×周期、每期应还、还款日。
入口也不同——它服务「建/编辑外部债」流里的「上传欠款截图」，而非「记支出拍小票」。

零新 OCR 基建：本地视觉模型走共享的 ``app.services.local_llm_vision`` 引擎（与小票
provider 同一台模型），本模块只拥有「账单 prompt + 账单 JSON→建议字段」这一层。

§8 红线：解析结果是**建议非事实**。模型可能编数字（财务危险），故 prompt 要求回
``source_text`` 源文本片段，且最终由用户在建债表单确认/改后才落账——本服务永不建债。
provider 默认 ``empty``（未配视觉模型即回落手填，不破坏手动建债闭环）。
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import get_settings
from app.services.local_llm_vision import call_local_llm_vision

# 与 DebtCreateRequest 对齐的上界：期数 le=600、周期 le=120（见 schemas/_debts.py），
# 还款日按安全 day-of-month（1..28，避开 29-31 的月份歧义）。
_MAX_INSTALLMENT_COUNT = 600
_MAX_INSTALLMENT_PERIOD_MONTHS = 120
_MAX_REPAYMENT_DAY = 28
# 单笔个人欠款金额的离谱上界（1 亿元），挡模型编出的天文数字；与业务真上界无关，
# 只防 UI 预填一个荒谬值。
_MAX_AMOUNT_CENTS = 100_000_000_00


@dataclass(frozen=True)
class DebtBillSuggestion:
    """一张债务账单解析出的**建议**字段（全部可空——缺字段即留给用户手填）。

    ``source_text`` 是模型回的关键源文本片段（§D point 3：防 rubber-stamp / 编数字）。
    """

    merchant: str | None = None
    principal_amount_cents: int | None = None
    installment_count: int | None = None
    installment_period_months: int | None = None
    per_period_amount_cents: int | None = None
    repayment_day: int | None = None
    source_text: str = ""
    confidence: float | None = None


class DebtBillProvider(Protocol):
    def parse(self, image_bytes: bytes, media_type: str | None = None) -> DebtBillSuggestion:
        ...


class EmptyDebtBillProvider:
    """默认 provider：不调任何模型，返回空建议。

    «没配视觉模型→回落手填»的形态——端点仍返回 200，建债表单保持空白由用户填。
    """

    def parse(self, image_bytes: bytes, media_type: str | None = None) -> DebtBillSuggestion:
        return DebtBillSuggestion()


class MockDebtBillProvider:
    """确定性 dev/test provider——不调模型（§8 要求每个 provider 至少 empty + mock）。

    合成一张「花呗 12 期」账单建议，供 UI / 端到端流程在不起视觉模型时演练。
    """

    def parse(self, image_bytes: bytes, media_type: str | None = None) -> DebtBillSuggestion:
        return DebtBillSuggestion(
            merchant="花呗",
            principal_amount_cents=120000,
            installment_count=12,
            installment_period_months=1,
            per_period_amount_cents=10000,
            repayment_day=10,
            source_text="花呗分期 12期 每期￥100.00 每月10日还款",
            confidence=0.5,
        )


class LocalLlmDebtBillProvider:
    """生产 provider：走共享视觉引擎，账单 prompt + 账单 JSON 映射。"""

    def parse(self, image_bytes: bytes, media_type: str | None = None) -> DebtBillSuggestion:
        parsed_json = call_local_llm_vision(image_bytes, media_type, _debt_bill_prompt_text())
        return _suggestion_from_llm_json(parsed_json)


def _debt_bill_prompt_text() -> str:
    return (
        "You are Xiaopiaojia's debt-bill parser. The image is a Chinese consumer "
        "debt / installment statement (花呗 / 白条 / 信用卡分期 / 网贷等). Extract the "
        "repayment terms and return JSON ONLY, no explanation, no markdown fence. "
        "Fields: merchant(string|null, the platform / card issuer, e.g. 花呗 / 招商银行信用卡), "
        "principal_amount_cents(int|null, the total amount owed in minor units / 分; "
        "greater than 0 when present, null when unknown, never 0), "
        "installment_count(int|null, 总期数), "
        "installment_period_months(int|null, 每期月数, usually 1 for 按月), "
        "per_period_amount_cents(int|null, 每期应还 in minor units / 分; greater than 0 or null), "
        "repayment_day(int|null, 每月还款日, 1-28), "
        "source_text(string, the exact text fragments from the image that the numbers "
        "above were read from — do NOT invent or summarise, copy what you see), "
        "confidence(number 0-1). Read only what the image shows; when a field is not "
        "visible, return null — do not guess."
    )


def _suggestion_from_llm_json(payload: Mapping[str, object]) -> DebtBillSuggestion:
    return DebtBillSuggestion(
        merchant=_coerce_optional_text(payload.get("merchant")),
        principal_amount_cents=_coerce_amount_cents(payload.get("principal_amount_cents")),
        installment_count=_coerce_bounded_int(
            payload.get("installment_count"), low=1, high=_MAX_INSTALLMENT_COUNT
        ),
        installment_period_months=_coerce_bounded_int(
            payload.get("installment_period_months"), low=1, high=_MAX_INSTALLMENT_PERIOD_MONTHS
        ),
        per_period_amount_cents=_coerce_amount_cents(payload.get("per_period_amount_cents")),
        repayment_day=_coerce_bounded_int(
            payload.get("repayment_day"), low=1, high=_MAX_REPAYMENT_DAY
        ),
        source_text=str(payload.get("source_text") or ""),
        confidence=_coerce_float(payload.get("confidence")),
    )


def _coerce_optional_text(value: Any) -> str | None:
    coerced: str | None = None
    if value is not None:
        text = str(value).strip()
        if text and text.lower() != "null":
            coerced = text
    return coerced


def _coerce_int(value: Any) -> int | None:
    coerced: int | None = None
    if value is not None:
        with suppress(TypeError, ValueError):
            coerced = int(value)
    return coerced


def _coerce_amount_cents(value: Any) -> int | None:
    amount = _coerce_int(value)
    if amount is not None and 0 < amount <= _MAX_AMOUNT_CENTS:
        return amount
    return None


def _coerce_bounded_int(value: Any, *, low: int, high: int) -> int | None:
    number = _coerce_int(value)
    if number is not None and low <= number <= high:
        return number
    return None


def _coerce_float(value: Any) -> float | None:
    coerced: float | None = None
    if value is not None:
        with suppress(TypeError, ValueError):
            coerced = max(0.0, min(1.0, float(value)))
    return coerced


def get_debt_bill_provider(provider_name: str | None = None) -> DebtBillProvider:
    name = (provider_name or get_settings().debt_bill_provider).strip().lower()
    if name == "mock":
        return MockDebtBillProvider()
    if name in {"local_llm", "local_vlm", "vlm"}:
        return LocalLlmDebtBillProvider()
    return EmptyDebtBillProvider()


def parse_debt_bill(
    image_bytes: bytes, media_type: str | None = None, provider_name: str | None = None
) -> DebtBillSuggestion:
    """用配置的 provider 解析一张债务账单图，返回建议字段。

    用户主动发起的解析——provider 失败（视觉模型不可用 / 队列繁忙）按 ``AppError``
    上抛由路由返回「识别失败」，不静默吞错；这不破坏 §8 主闭环，因为手动建债不依赖
    解析（用户可直接手填）。
    """

    return get_debt_bill_provider(provider_name).parse(image_bytes, media_type)
