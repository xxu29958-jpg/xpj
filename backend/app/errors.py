from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class Utf8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


ERROR_MESSAGES = {
    "exchange_rate_pending": "Exchange rate is still pending. Please retry after the backend sync completes.",
    "invalid_token": "登录已失效，请重新绑定设备。",
    "legacy_auth_removed": "旧版访问方式已停用，请重新绑定。",
    "bootstrap_already_initialized": "小票夹已经初始化过了。",
    "bootstrap_disabled": "初始化入口已关闭，请使用本机脚本。",
    "bootstrap_secret_required": "缺少一次性初始化口令。",
    "invalid_bootstrap_secret": "初始化口令无效或已使用。",
    "invalid_pairing_code": "绑定码无效，请重新生成。",
    "pairing_code_expired": "绑定码已过期，请重新生成。",
    "pairing_code_used": "绑定码已被使用，请重新生成。",
    "file_too_large": "图片太大，请换一张较小的截图。",
    "unsupported_file_type": "暂不支持这种图片格式。",
    "expense_not_found": "没有找到这笔账单。",
    "amount_required": "请先填写金额。",
    "amount_invalid": "金额格式不正确。",
    "currency_not_supported": "暂不支持这个币种。",
    "exchange_rate_required": "请先填写这一天的汇率。",
    "exchange_rate_invalid": "汇率格式不正确。",
    "exchange_rate_base_currency": "人民币是基准币种，不需要维护汇率。",
    "image_not_found": "图片不存在或已被清理。",
    "ocr_not_configured": "未配置 OCR，请在后端启用 OCR_PROVIDER 后再重试。",
    "rule_not_found": "分类规则不存在。",
    "rule_application_not_found": "规则应用批次不存在。",
    "rule_in_use": "分类规则仍在使用，不能删除。",
    "admin_api_local_only": "管理接口仅允许本机访问。",
    "server_error": "服务器开小差了，请稍后再试。",
    "invalid_request": "请求参数不正确。",
    "route_not_found": "没有找到这个功能入口。",
    "method_not_allowed": "这个入口不支持当前操作。",
    "ledger_not_found": "账本不存在或没有访问权限。",
    "ledger_name_required": "请填写账本名称。",
    "ledger_name_too_long": "账本名称过长，请控制在 60 个字以内。",
    "ledger_forbidden": "当前账号没有该账本的访问权限。",
    "permission_denied": "当前角色为只读，无法修改账本。",
    "invitation_invalid": "邀请码无效、已过期或已被使用。",
    "invitation_role_invalid": "邀请角色只能是成员或只读。",
    "invitation_note_too_long": "备注最多 80 个字。",
    "member_not_found": "成员不存在或已停用。",
    "ledger_member_role_invalid": "账本成员角色无效。",
    "member_cannot_disable_self": "不能停用账本的最后一位 owner。",
    "member_cannot_disable_owner": "不能停用账本的 owner。",
    "member_role_invalid": "成员角色只能是成员或只读。",
    "member_cannot_change_owner_role": "owner 角色不能通过普通角色调整修改。",
    "owner_transfer_requires_owner": "只有当前 owner 可以转让账本。",
    "owner_transfer_self": "不能把 owner 转让给自己。",
    "owner_transfer_target_invalid": "只能转让给当前账本的活跃非 owner 成员。",
    "recurring_candidate_not_found": "没有找到可确认的固定支出候选。",
    "recurring_item_not_found": "固定支出不存在。",
    "recurring_frequency_invalid": "固定支出周期暂不支持。",
    "recurring_status_invalid": "固定支出状态无效。",
    "recurring_item_archived": "固定支出已归档，不能继续修改。",
    "goal_not_found": "目标不存在。",
    "notification_source_invalid": "通知来源暂不支持。",
    "merchant_alias_not_found": "商家别名不存在。",
    "merchant_alias_conflict": "商家别名已指向其他商家。",
    "import_batch_not_found": "导入批次不存在。",
    "state_conflict": "记录已被其它端修改，请刷新后再试。",
    "ai_advisor_not_confirmed": "AI 预算助手尚未经过 owner 显式确认，已禁用。",
    "ai_advisor_owner_required": "只有账本 owner 可以调用外部 AI 预算建议。",
    "ai_advisor_rate_limited": "AI 预算助手调用过于频繁，请稍后再试。",
    "ai_advisor_daily_limit_exceeded": "AI 预算助手今日调用次数已达上限。",
}


class AppError(Exception):
    """API-surface error: the FastAPI exception handler turns these into
    JSON ``{error, message}`` payloads with the matching HTTP status."""

    def __init__(self, error: str, message: str | None = None, status_code: int = 400) -> None:
        self.error = error
        self.message = message or ERROR_MESSAGES.get(error, ERROR_MESSAGES["server_error"])
        self.status_code = status_code
        super().__init__(self.message)


class DataIntegrityError(RuntimeError):
    """Legacy data on disk does not match the invariants the runtime requires.

    Raised exclusively during ``init_db`` / migration / validation. Inherits
    from ``RuntimeError`` so existing ``except RuntimeError`` blocks (notably
    the ``test_database_migration_*.py`` suite's ``pytest.raises(RuntimeError, match=...)``)
    keep working. New call sites can ``except DataIntegrityError`` to
    distinguish migration-time data corruption from other RuntimeErrors.
    """


class PathTraversalError(RuntimeError):
    """A computed filesystem target escaped the configured boundary.

    Security-sensitive condition raised when an upload or backup path
    resolution leaves the directory we explicitly confined it to. Subclass
    of RuntimeError for backwards compatibility with prior `except
    RuntimeError` callers; should be re-raised, never swallowed.
    """


def error_response(
    error: str,
    message: str | None = None,
    status_code: int = 400,
    *,
    request_id: str | None = None,
) -> JSONResponse:
    content: dict[str, str] = {
        "error": error,
        "message": message or ERROR_MESSAGES.get(error, ERROR_MESSAGES["server_error"]),
    }
    if request_id:
        # Echo back to make screenshots / chat reports actionable; the same
        # value is on the X-Request-Id response header set by the logging
        # middleware. See ENGINEERING_RULES §12.
        content["request_id"] = request_id
    return Utf8JSONResponse(status_code=status_code, content=content)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.error, exc.message, exc.status_code, request_id=_request_id(request))


async def validation_error_handler(request: Request, __: RequestValidationError) -> JSONResponse:
    return error_response(
        "invalid_request",
        ERROR_MESSAGES["invalid_request"],
        422,
        request_id=_request_id(request),
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = _request_id(request)
    if exc.status_code in {401, 403}:
        return error_response("invalid_token", ERROR_MESSAGES["invalid_token"], exc.status_code, request_id=request_id)
    if exc.status_code == 404:
        return error_response("route_not_found", ERROR_MESSAGES["route_not_found"], exc.status_code, request_id=request_id)
    if exc.status_code == 405:
        return error_response("method_not_allowed", ERROR_MESSAGES["method_not_allowed"], exc.status_code, request_id=request_id)
    return error_response("invalid_request", str(exc.detail), exc.status_code, request_id=request_id)


async def unhandled_error_handler(request: Request, __: Exception) -> JSONResponse:
    return error_response(
        "server_error",
        ERROR_MESSAGES["server_error"],
        500,
        request_id=_request_id(request),
    )


def add_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
