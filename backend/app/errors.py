from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class Utf8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


ERROR_MESSAGES = {
    "invalid_token": "Token 无效。",
    "legacy_auth_removed": "请使用新版绑定方式。",
    "bootstrap_already_initialized": "Owner 已初始化。",
    "bootstrap_disabled": "Bootstrap 接口已禁用。",
    "bootstrap_secret_required": "缺少一次性 bootstrap secret。",
    "invalid_bootstrap_secret": "Bootstrap secret 无效或已使用。",
    "invalid_pairing_code": "绑定码无效。",
    "pairing_code_expired": "绑定码已过期。",
    "pairing_code_used": "绑定码已使用。",
    "file_too_large": "上传文件超过大小限制。",
    "unsupported_file_type": "不支持的图片格式。",
    "expense_not_found": "账单不存在。",
    "amount_required": "请先填写金额。",
    "image_not_found": "图片不存在。",
    "rule_not_found": "分类规则不存在。",
    "rule_in_use": "分类规则仍在使用，不能删除。",
    "server_error": "服务器内部错误。",
    "invalid_request": "请求参数不正确。",
    "route_not_found": "接口不存在。",
    "method_not_allowed": "请求方法不允许。",
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
