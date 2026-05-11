from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class Utf8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


ERROR_MESSAGES = {
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
    "image_not_found": "图片不存在或已被清理。",
    "rule_not_found": "分类规则不存在。",
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
    "permission_denied": "当前角色无权进行此操作。",
    "invitation_invalid": "邀请码无效、已过期或已被使用。",
    "invitation_role_invalid": "邀请角色只能是成员或只读。",
    "invitation_note_too_long": "备注最多 80 个字。",
    "member_not_found": "成员不存在或已停用。",
    "member_cannot_disable_self": "不能停用账本的最后一位 owner。",
    "member_cannot_disable_owner": "不能停用账本的 owner。",
}


class AppError(Exception):
    def __init__(self, error: str, message: str | None = None, status_code: int = 400) -> None:
        self.error = error
        self.message = message or ERROR_MESSAGES.get(error, ERROR_MESSAGES["server_error"])
        self.status_code = status_code
        super().__init__(self.message)


def error_response(error: str, message: str | None = None, status_code: int = 400) -> JSONResponse:
    return Utf8JSONResponse(
        status_code=status_code,
        content={
            "error": error,
            "message": message or ERROR_MESSAGES.get(error, ERROR_MESSAGES["server_error"]),
        },
    )


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.error, exc.message, exc.status_code)


async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return error_response("invalid_request", ERROR_MESSAGES["invalid_request"], 422)


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code in {401, 403}:
        return error_response("invalid_token", ERROR_MESSAGES["invalid_token"], exc.status_code)
    if exc.status_code == 404:
        return error_response("route_not_found", ERROR_MESSAGES["route_not_found"], exc.status_code)
    if exc.status_code == 405:
        return error_response("method_not_allowed", ERROR_MESSAGES["method_not_allowed"], exc.status_code)
    return error_response("invalid_request", str(exc.detail), exc.status_code)


async def unhandled_error_handler(_: Request, __: Exception) -> JSONResponse:
    return error_response("server_error", ERROR_MESSAGES["server_error"], 500)


def add_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
