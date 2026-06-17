from __future__ import annotations

from html import escape as _html_escape

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class Utf8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


ERROR_MESSAGES = {
    "split_amount_invalid": "请填写大于 0 的拆账金额。",
    "split_receiver_invalid": "对方现在不能接收拆账邀请。",
    "split_parent_amount_missing": "原账单金额未确定，无法发起拆账。",
    "split_amount_exceeds_parent": "拆账金额不能超过原账单金额。",
    "split_total_exceeds_parent": "拆账邀请总额不能超过原账单金额。",
    "split_status_invalid": "拆账邀请状态不正确。",
    "split_invitation_already_pending": "已有发给对方的待处理拆账邀请。",
    "invitation_not_found": "拆账邀请不存在或已被清理。",
    "invitation_not_yours": "没有权限操作这条拆账邀请。",
    "invitation_not_acceptable": "拆账邀请已被处理，无法再接受或拒绝。",
    "invitation_not_cancellable": "拆账邀请已被对方处理，无法撤回。",
    "invitation_expired": "拆账邀请已过期。",
    "bill_split_owner_account_missing": "未找到可发起拆账的拥有者账号。",
    "exchange_rate_pending": "汇率还没同步完成，稍后再确认。",
    "invalid_token": "登录已失效，请重新绑定设备。",
    "legacy_auth_removed": "旧版访问方式已停用，请重新绑定。",
    "bootstrap_already_initialized": "小票夹已经初始化过了。",
    "bootstrap_disabled": "初始化入口已关闭，请使用本机脚本。",
    "bootstrap_secret_required": "缺少一次性初始化口令。",
    "invalid_bootstrap_secret": "初始化口令无效或已使用。",
    "invalid_pairing_code": "绑定码无效，请重新生成。",
    "rate_limited": "尝试太频繁，请稍后再试。",
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
    "ocr_not_configured": "图片识别功能还没开启，请联系服务拥有者在电脑端开启后再试。",
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
    "cannot_archive_default_ledger": "默认账本不能归档，它是系统的兜底账本。",
    "permission_denied": "当前角色为只读，无法修改账本。",
    "invitation_invalid": "邀请码无效、已过期或已被使用。",
    "invitation_role_invalid": "邀请角色只能是成员或只读。",
    "invitation_note_too_long": "备注最多 80 个字。",
    "member_not_found": "成员不存在或已停用。",
    "ledger_member_role_invalid": "账本成员角色无效。",
    "member_cannot_disable_self": "不能停用账本的最后一位拥有者。",
    "member_cannot_disable_owner": "不能停用账本的拥有者。",
    "member_role_invalid": "成员角色只能是成员或只读。",
    "member_cannot_change_owner_role": "拥有者角色不能通过普通角色调整修改。",
    "owner_transfer_requires_owner": "只有当前拥有者可以转让账本。",
    "owner_transfer_self": "不能把拥有者转让给自己。",
    "owner_transfer_target_invalid": "只能转让给当前账本的活跃非拥有者成员。",
    "recurring_candidate_not_found": "没有找到可确认的固定支出候选。",
    "recurring_item_not_found": "固定支出不存在。",
    "recurring_frequency_invalid": "固定支出周期暂不支持。",
    "recurring_status_invalid": "固定支出状态无效。",
    "recurring_item_archived": "固定支出已归档，不能继续修改。",
    "goal_not_found": "目标不存在。",
    # ADR-0049 Debt domain (slice 1: external/manual Debt create/list/get).
    "debt_not_found": "这笔欠款不存在。",
    "debt_counterparty_invalid": "欠款对象信息不完整。",
    "debt_amount_invalid": "请填写大于 0 的欠款金额。",
    "debt_direction_invalid": "欠款方向不正确。",
    # ADR-0049 Debt domain (slice 2: repayment / adjustment / void facts). A
    # stale ``expected_row_version`` and writing on a voided Debt reuse the
    # generic ``state_conflict`` below.
    "debt_overpay_rejected": "还款金额超过剩余欠款。",
    "debt_adjustment_negative_remaining": "调整后欠款金额不能为负。",
    "debt_reason_required": "请填写原因。",
    "repayment_not_found": "还款记录不存在。",
    "repayment_already_voided": "这笔还款已被作废。",
    "debt_already_voided": "这笔欠款已作废，无法继续操作。",
    # ADR-0049 Debt domain (slice 3: member repayment proposal §3.2). A stale
    # ``expected_row_version`` on confirm reuses the generic ``state_conflict``;
    # an overpay reuses ``debt_overpay_rejected``; a pending FX rate reuses
    # ``exchange_rate_pending``. These cover the proposal-specific cases.
    "repayment_proposal_requires_member_debt": "只有家庭成员之间的欠款才能发起还款确认。",
    "repayment_proposal_debtor_only": "只有欠款一方可以发起或撤回还款申请。",
    "repayment_proposal_creditor_only": "只有收款一方可以确认或拒绝还款申请。",
    "repayment_proposal_not_found": "还款申请不存在或已被处理。",
    "repayment_proposal_not_pending": "这条还款申请已被处理，无法再操作。",
    "repayment_proposal_expired": "还款申请已过期，请重新发起。",
    "repayment_proposal_amount_invalid": "请填写正确的还款金额。",
    "repayment_proposal_already_pending": "已有一条待处理的还款申请。",
    # ADR-0049 §杠杆③ (slice 3a): NLS-captured repayment review inbox. A stale
    # ``expected_row_version`` on confirm and re-resolving an already-resolved draft
    # reuse the generic ``state_conflict``; an invalid capture channel reuses
    # ``notification_source_invalid``; an overpay reuses ``debt_overpay_rejected``.
    "repayment_draft_not_found": "这条还款记录不存在或已处理。",
    "notification_source_invalid": "通知来源暂不支持。",
    "merchant_alias_not_found": "商家别名不存在。",
    "merchant_alias_conflict": "商家别名已指向其他商家。",
    # ADR-0043 tag management (online-only rename/delete/merge/undo). A stale
    # OCC token on rename/delete/merge/undo reuses the generic ``state_conflict``;
    # these cover the tag-specific not-found / name-collision / undo-window cases.
    "tag_not_found": "标签不存在。",
    "tag_conflict": "已有同名标签，可改为合并。",
    "tag_undo_not_found": "撤销记录不存在或已超过可撤销时间。",
    "import_batch_not_found": "导入批次不存在。",
    "not_found": "没有找到对应的记录。",
    "task_not_found": "后台任务不存在或已结束。",
    "state_conflict": "记录已被其它端修改，请刷新后再试。",
    # ADR-0042 request-idempotency (Idempotency-Key header on outbox-routed
    # mutate面). These are protocol-level errors the client/outbox consumes —
    # the user never sees them in normal flow (Android always sends the key).
    "idempotency_key_required": "请求缺少幂等键，请重试。",
    "idempotency_key_in_progress": "操作正在处理中，请稍后再试。",
    "idempotency_key_reused": "幂等键已被另一请求使用，请勿复用。",
    "ai_advisor_not_confirmed": "AI 预算助手尚未经过拥有者显式确认，已禁用。",
    "ai_advisor_owner_required": "只有账本拥有者可以调用外部 AI 预算建议。",
    "ai_advisor_rate_limited": "AI 预算助手调用过于频繁，请稍后再试。",
    "ai_advisor_daily_limit_exceeded": "AI 预算助手今日调用次数已达上限。",
}


class AppError(Exception):
    """API-surface error: the FastAPI exception handler turns these into
    JSON ``{error, message}`` payloads with the matching HTTP status."""

    def __init__(
        self,
        error: str,
        message: str | None = None,
        status_code: int = 400,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        self.error = error
        self.message = message or ERROR_MESSAGES.get(error, ERROR_MESSAGES["server_error"])
        self.status_code = status_code
        # Optional extra body fields (e.g. ADR-0043 rename-conflict returns the
        # existing tag's public_id + row_version so the client can offer a merge).
        self.details = details
        super().__init__(self.message)


class DataIntegrityError(RuntimeError):
    """Legacy data on disk does not match the invariants the runtime requires.

    Raised exclusively during ``init_db`` / migration / validation. Inherits
    from ``RuntimeError`` so existing ``except RuntimeError`` blocks keep
    working. New call sites can ``except DataIntegrityError`` to distinguish
    migration-time data corruption from other RuntimeErrors.
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
    details: dict[str, object] | None = None,
) -> JSONResponse:
    content: dict[str, object] = {
        "error": error,
        "message": message or ERROR_MESSAGES.get(error, ERROR_MESSAGES["server_error"]),
    }
    if request_id:
        # Echo back to make screenshots / chat reports actionable; the same
        # value is on the X-Request-Id response header set by the logging
        # middleware. See ENGINEERING_RULES §12.
        content["request_id"] = request_id
    if details:
        # Extra structured fields (e.g. ADR-0043 tag rename-conflict target).
        # Reserved keys above win; details never overwrites error/message/request_id.
        for key, value in details.items():
            content.setdefault(key, value)
    return Utf8JSONResponse(status_code=status_code, content=content)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# ── Browser-friendly error pages (A3 fallback) ───────────────────────────────
#
# High-traffic /web write paths already convert errors into a 303-flash redirect
# back to the originating list (batches #37 / #44 / #47). What was left exposed
# was the *bottom* layer: a browser that lands on a /web (or /owner) URL with no
# matching route (404), or hits an uncaught 500, would see the raw JSON envelope
# instead of a page. This adds a minimal self-contained HTML page for exactly
# that case. Everything else — /api, /u, Android (OkHttp sends no Accept
# header by default, so it lands in the no-Accept bucket), shortcuts — keeps
# the byte-identical JSON envelope (ENGINEERING_RULES §4 contract; the Android
# ErrorResponse decoder must never receive HTML).

_HTML_ERROR_PREFIXES = ("/web", "/owner")
_VALID_UI_THEMES = frozenset({"paper", "mono", "midnight"})


def _wants_html_error_page(request: Request) -> bool:
    """True only when a browser on a /web or /owner URL prefers HTML.

    Simplified Accept negotiation (per A3 scope): a substring match on
    ``text/html`` is enough — real browsers always send it with a high weight,
    and our only non-browser callers on these prefixes are tests. The path gate
    is the hard guarantee that no /api or /u (Android / UploadLink / shortcuts)
    response is ever turned into HTML, regardless of a forged Accept header.
    """
    path = request.url.path
    if not (path == "/web" or path == "/owner" or any(path.startswith(p + "/") for p in _HTML_ERROR_PREFIXES)):
        return False
    accept = request.headers.get("accept", "")
    return "text/html" in accept.lower()


def _error_page_theme(request: Request) -> str:
    """Mirror web_common._read_ui_theme without importing it.

    Importing app.routes.web_common here would drag the whole /web service tree
    into this bottom-layer module at import time and form an import cycle
    (web_common imports app.errors.AppError). The cookie read is two lines, so
    we inline it. Absent/garbled cookie → the 'paper' default, same as /web.
    """
    raw = request.cookies.get("ui_theme")
    return raw if raw in _VALID_UI_THEMES else "paper"


# Status → (page <title> / 大标题, 一句下一步). Generic buckets cover anything
# not called out explicitly. Copy is "生活 App" voice per §10 — never leaks the
# status number, route name, host path, or a stack trace.
_ERROR_PAGE_COPY = {
    403: ("没有权限", "这个账本或页面当前账号无法访问。"),
    404: ("这个页面不存在", "链接可能已经失效，或者地址打错了。"),
    500: ("暂时出了点问题", "刚才的操作没能完成，请稍后再试。"),
}
_GENERIC_4XX_COPY = ("请求无法完成", "这个操作现在没法处理，请返回后重试。")
_GENERIC_5XX_COPY = _ERROR_PAGE_COPY[500]


def _error_page_copy(status_code: int) -> tuple[str, str]:
    if status_code in _ERROR_PAGE_COPY:
        return _ERROR_PAGE_COPY[status_code]
    if status_code >= 500:
        return _GENERIC_5XX_COPY
    return _GENERIC_4XX_COPY


def html_error_response(request: Request, status_code: int) -> HTMLResponse:
    """Render the minimal browser error page for /web and /owner.

    Self-contained: links the shared design tokens so all three themes apply,
    carries ``data-theme`` from the ui_theme cookie (paper default), and shows
    the request_id in small text so a screenshot is actionable (§12). No body
    field exposes internals (§4 / §10).
    """
    heading, hint = _error_page_copy(status_code)
    theme = _error_page_theme(request)
    request_id = _request_id(request)
    # "回到首页" must land on the surface the user was on: the /owner console is
    # loopback-only and has its own home — sending its errors to /web would 303
    # the operator into the session-gated user surface.
    path = request.url.path
    home_href = "/owner" if path == "/owner" or path.startswith("/owner/") else "/web"
    rid_line = (
        f'<p class="error-page__rid">问题编号 {_html_escape(request_id)}</p>' if request_id else ""
    )
    body = (
        "<!DOCTYPE html>"
        f'<html lang="zh-CN" data-theme="{_html_escape(theme)}">'
        "<head>"
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f"<title>{_html_escape(heading)} · 小票夹</title>"
        '<link rel="stylesheet" href="/static/shared/tokens.css">'
        "<style>"
        # Consume the real shared tokens (--surface-app / --text-* / --brand-* /
        # --radius-*) so paper/mono/midnight all theme correctly via data-theme;
        # literal fallbacks mirror the paper palette if a token is ever absent.
        # Font family stays a local system stack (tokens.css keeps font-family per-end).
        "body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;"
        "background:var(--surface-app,#f8f7f4);color:var(--text-default,#21201c);"
        "font-family:system-ui,-apple-system,'Segoe UI',sans-serif;}"
        ".error-page{max-width:30rem;padding:2.5rem 1.5rem;text-align:center;}"
        ".error-page__title{font-size:var(--type-headline-size,22px);font-weight:700;margin:0 0 .5rem;}"
        ".error-page__hint{font-size:1rem;line-height:1.6;color:var(--text-muted,#63635e);margin:0 0 1.75rem;}"
        ".error-page__home{display:inline-block;padding:.6rem 1.4rem;border-radius:var(--radius-md,10px);"
        "background:var(--brand-primary,#a0561f);color:var(--text-on-primary,#fff);"
        "text-decoration:none;font-weight:600;}"
        ".error-page__rid{margin:1.75rem 0 0;font-size:.8rem;color:var(--text-meta,#9c9b96);}"
        "</style>"
        "</head>"
        '<body><main class="error-page">'
        f'<h1 class="error-page__title">{_html_escape(heading)}</h1>'
        f'<p class="error-page__hint">{_html_escape(hint)}</p>'
        f'<a class="error-page__home" href="{home_href}">回到首页</a>'
        f"{rid_line}"
        "</main></body></html>"
    )
    return HTMLResponse(content=body, status_code=status_code)


async def app_error_handler(request: Request, exc: AppError) -> Response:
    if exc.status_code >= 400 and _wants_html_error_page(request):
        return html_error_response(request, exc.status_code)
    return error_response(
        exc.error,
        exc.message,
        exc.status_code,
        request_id=_request_id(request),
        details=exc.details,
    )


async def validation_error_handler(request: Request, __: RequestValidationError) -> Response:
    if _wants_html_error_page(request):
        return html_error_response(request, 422)
    return error_response(
        "invalid_request",
        ERROR_MESSAGES["invalid_request"],
        422,
        request_id=_request_id(request),
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> Response:
    if _wants_html_error_page(request):
        return html_error_response(request, exc.status_code)
    request_id = _request_id(request)
    if exc.status_code in {401, 403}:
        return error_response("invalid_token", ERROR_MESSAGES["invalid_token"], exc.status_code, request_id=request_id)
    if exc.status_code == 404:
        return error_response("route_not_found", ERROR_MESSAGES["route_not_found"], exc.status_code, request_id=request_id)
    if exc.status_code == 405:
        return error_response("method_not_allowed", ERROR_MESSAGES["method_not_allowed"], exc.status_code, request_id=request_id)
    return error_response("invalid_request", str(exc.detail), exc.status_code, request_id=request_id)


async def unhandled_error_handler(request: Request, __: Exception) -> Response:
    if _wants_html_error_page(request):
        return html_error_response(request, 500)
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
