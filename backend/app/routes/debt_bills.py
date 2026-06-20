"""ADR-0049 §D 债务账单 OCR 解析路由（瞬态——不落库、不建债、不存图）。

薄路由层（§1）：解析上传图、鉴权、调 ``debt_bill_parse_service``、返回 schema；不写
业务、不落库。这是「上传欠款截图 → 建议还款条款 → 预填建/编外部债表单」的解析入口，
建债仍走 ``POST /api/debts``（用户在表单确认/改之后）。§8：解析结果是建议非事实。

挂在独立路由文件而非 ``debts.py``：账单解析与债务 CRUD/事实写是不同关注点，且
``debts.py`` 已大；``/api/debts/parse-bill`` 是字面段，与 ``/{public_id}`` 模式不冲突。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from app.auth import get_current_writer_context
from app.config import get_settings
from app.errors import AppError
from app.schemas import DebtBillParseResponse
from app.services.debt_bill_parse_service import DebtBillSuggestion, parse_debt_bill
from app.tenants import AuthContext

router = APIRouter(prefix="/api/debts", tags=["debts"])


async def _read_image_upload(file: UploadFile) -> bytes:
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise AppError("unsupported_file_type", status_code=400)
    # Cap the read at limit+1 so an oversized upload is rejected without buffering
    # the whole body (mirrors uploads.py's max_upload_size_bytes bound).
    limit = get_settings().max_upload_size_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError("file_too_large", status_code=413)
    if not data:
        raise AppError("invalid_request", "上传的图片为空。", status_code=422)
    return data


def _suggestion_response(suggestion: DebtBillSuggestion) -> DebtBillParseResponse:
    return DebtBillParseResponse(
        merchant=suggestion.merchant,
        principal_amount_cents=suggestion.principal_amount_cents,
        installment_count=suggestion.installment_count,
        installment_period_months=suggestion.installment_period_months,
        per_period_amount_cents=suggestion.per_period_amount_cents,
        repayment_day=suggestion.repayment_day,
        source_text=suggestion.source_text,
        confidence=suggestion.confidence,
    )


@router.post("/parse-bill", response_model=DebtBillParseResponse)
async def post_parse_debt_bill(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_current_writer_context),
) -> DebtBillParseResponse:
    # 瞬态解析：读上传图 → provider 出建议字段 → 返回供前端预填建债表单。不落库、不建债、
    # 不挂 Debt（图也不存——slice 1 只做解析）。writer-context：只有可写成员能建债，故只有
    # 他们能解析（viewer 403 / 无 token 401）。auth 仅作鉴权门——解析无租户副作用，不取 db。
    image_bytes = await _read_image_upload(file)
    suggestion = parse_debt_bill(image_bytes, file.content_type)
    return _suggestion_response(suggestion)
