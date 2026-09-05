"""Owner Console for the closed service-owned runtime settings projection.

Lets the operator change a small set of operator-friendly settings without
granting the running backend write access to the lifecycle ``.env`` that also
contains database credentials.

Security:
- Only callable from Owner Console routes (loopback-only).
- The service-owned projection lives outside the web root and is never served.
- We only allow keys whitelisted in :data:`_EDITABLE_KEYS`.
- Values are validated before being written.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import (
    BACKEND_ROOT,
    DATA_ROOT,
    get_settings,
    runtime_settings_service_owned,
)
from app.errors import AppError
from app.recognition_config import resolve_local_llm_base_url
from app.services.runtime_settings_store import (
    RecognitionSettingsProjection,
    RuntimeSettingsMutation,
    RuntimeSettingsProjection,
    patch_runtime_settings,
)
from app.version import BACKEND_VERSION

_SETTINGS_PATH = DATA_ROOT / "runtime-settings" / "runtime-settings.json"
_SERVICE_OWNED = runtime_settings_service_owned()

_EDITABLE_KEYS: frozenset[str] = frozenset(
    {"BUDGET_ADVISOR_OWNER_CONFIRMED", "PUBLIC_BASE_URL", "RECOGNITION_PIPELINE"}
)


@dataclass(frozen=True)
class RuntimeSettingsView:
    public_base_url: str
    public_base_url_configured: bool
    settings_path: str
    settings_exists: bool


@dataclass(frozen=True)
class RecognitionSettingsForm:
    ocr_provider: str
    ocr_auto_run: bool
    ocr_fallback_provider: str
    ocr_min_confidence: str
    ocr_default_timezone: str
    local_llm_base_url: str
    local_llm_model: str
    local_llm_timeout_seconds: str
    local_llm_max_concurrent: str
    local_llm_queue_timeout_seconds: str
    debt_bill_provider: str


@dataclass(frozen=True)
class RecognitionSettingsView:
    form: RecognitionSettingsForm
    rapidocr_available: bool
    receipt_status: str
    debt_bill_status: str


@dataclass(frozen=True)
class SecurityView:
    allow_public_admin_api: bool
    enable_api_docs: bool
    enable_http_bootstrap: bool
    public_base_url_configured: bool


@dataclass(frozen=True)
class AboutView:
    backend_version: str
    backend_root: str
    database_url_masked: str
    upload_dir: str
    max_upload_size_mb: int


def _mask_db_url(raw: str) -> str:
    """Hide credentials in DATABASE_URL when displayed in the GUI."""
    if "@" not in raw:
        return raw
    head, _, tail = raw.partition("://")
    if not tail or "@" not in tail:
        return raw
    creds, _, host = tail.partition("@")
    return f"{head}://***@{host}"


def get_view() -> RuntimeSettingsView:
    cfg = get_settings()
    return RuntimeSettingsView(
        public_base_url=cfg.public_base_url,
        public_base_url_configured=bool(cfg.public_base_url),
        settings_path=str(_SETTINGS_PATH),
        settings_exists=_SETTINGS_PATH.is_file(),
    )


def get_recognition_view(
    form: RecognitionSettingsForm | None = None,
) -> RecognitionSettingsView:
    if form is None:
        cfg = get_settings()
        form = RecognitionSettingsForm(
            ocr_provider=cfg.ocr_provider,
            ocr_auto_run=cfg.ocr_auto_run,
            ocr_fallback_provider=cfg.ocr_fallback_provider,
            ocr_min_confidence=f"{cfg.ocr_min_confidence:g}",
            ocr_default_timezone=cfg.ocr_default_timezone,
            local_llm_base_url=cfg.local_llm_base_url,
            local_llm_model=cfg.local_llm_model,
            local_llm_timeout_seconds=str(cfg.local_llm_timeout_seconds),
            local_llm_max_concurrent=str(cfg.local_llm_max_concurrent),
            local_llm_queue_timeout_seconds=f"{cfg.local_llm_queue_timeout_seconds:g}",
            debt_bill_provider=cfg.debt_bill_provider,
        )
    if form.ocr_provider == "empty":
        receipt_status = "手动核对"
    elif not form.ocr_auto_run:
        receipt_status = "已配置，自动识别关闭"
    elif form.ocr_provider == "rapidocr":
        receipt_status = "自动使用本机 RapidOCR"
    else:
        receipt_status = "自动使用本机视觉模型"
    debt_bill_status = "本机视觉模型" if form.debt_bill_provider == "local_llm" else "手动录入"
    return RecognitionSettingsView(
        form=form,
        rapidocr_available=importlib.util.find_spec("rapidocr") is not None,
        receipt_status=receipt_status,
        debt_bill_status=debt_bill_status,
    )


def get_security_view() -> SecurityView:
    cfg = get_settings()
    return SecurityView(
        allow_public_admin_api=cfg.allow_public_admin_api,
        enable_api_docs=cfg.enable_api_docs,
        enable_http_bootstrap=cfg.enable_http_bootstrap,
        public_base_url_configured=bool(cfg.public_base_url),
    )


def get_about_view() -> AboutView:
    cfg = get_settings()
    return AboutView(
        backend_version=BACKEND_VERSION,
        backend_root=str(BACKEND_ROOT),
        database_url_masked=_mask_db_url(cfg.database_url),
        upload_dir=str(cfg.upload_dir),
        max_upload_size_mb=cfg.max_upload_size_mb,
    )


_LOOPBACK_HOST_NAMES = frozenset({"127.0.0.1", "::1", "localhost"})


def _validate_public_base_url(raw: str) -> str:
    """Validate and normalise PUBLIC_BASE_URL.

    Only an *origin* (scheme + host + optional port) is accepted. Paths,
    query strings and fragments are rejected to prevent accidental
    misconfiguration that would produce malformed upload URLs.

    ``http://`` is only accepted when the host is a loopback alias (local
    dev). Public hostnames must use ``https://`` — UploadLink URLs include
    the ``upload_key`` in the path, which is a credential.

    Allowed:   HTTPS origin for the public host, or an HTTP loopback origin.
    Rejected:  public HTTP downgrade, trailing path, query string, or fragment.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    if not (value.startswith("http://") or value.startswith("https://")):
        raise AppError(
            "invalid_request",
            "公网域名必须以 http:// 或 https:// 开头。",
            status_code=422,
        )
    if " " in value or "\n" in value or "\r" in value:
        raise AppError("invalid_request", "公网域名不能包含空格或换行。", status_code=422)
    parsed = urlparse(value)
    if not parsed.netloc:
        raise AppError(
            "invalid_request",
            "公网域名必须包含主机名，例如填写你的 HTTPS 公网域名。",
            status_code=422,
        )
    if parsed.username or parsed.password:
        raise AppError("invalid_request", "公网域名不能包含用户名或密码。", status_code=422)
    try:
        _ = parsed.port
    except ValueError as exc:
        raise AppError("invalid_request", "公网域名端口不合法。", status_code=422) from exc
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in _LOOPBACK_HOST_NAMES:
        raise AppError(
            "invalid_request",
            "公网域名必须使用 https://；http:// 只允许本机环回（127.0.0.1 / localhost / ::1）。"
            "UploadLink URL 含一次性凭证，明文 http 走公网会被中间人截获。",
            status_code=422,
        )
    if parsed.path.rstrip("/"):
        raise AppError(
            "invalid_request",
            "公网域名只能填写域名根（不允许带路径），例如填写你的 HTTPS 公网域名。",
            status_code=422,
        )
    if parsed.query or parsed.fragment:
        raise AppError(
            "invalid_request",
            "公网域名不能包含查询参数或 # 片段。",
            status_code=422,
        )
    # Return scheme+netloc only (strips any trailing slash in path)
    return f"{parsed.scheme}://{parsed.netloc}"


def _write_runtime_value(key: str, value: str) -> RuntimeSettingsProjection:
    if key not in _EDITABLE_KEYS:
        raise AppError(
            "invalid_request",
            "This setting cannot be changed from Owner Console.",
            status_code=403,
        )
    settings = get_settings()
    defaults = RuntimeSettingsProjection(
        public_base_url=settings.public_base_url,
        budget_advisor_owner_confirmed=settings.budget_advisor_owner_confirmed,
    )
    mutation = RuntimeSettingsMutation(
        field=("public_base_url" if key == "PUBLIC_BASE_URL" else "budget_advisor_owner_confirmed"),
        value=value if key == "PUBLIC_BASE_URL" else value == "true",
    )
    projection = patch_runtime_settings(
        _SETTINGS_PATH,
        defaults=defaults,
        mutation=mutation,
        service_owned=_SERVICE_OWNED,
    )
    get_settings.cache_clear()  # type: ignore[attr-defined]
    return projection


def _invalid(message: str) -> AppError:
    return AppError("invalid_request", message, status_code=422)


def _bounded_int(raw: str, *, label: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{label}必须是整数。") from exc
    if not minimum <= value <= maximum:
        raise _invalid(f"{label}必须在 {minimum}–{maximum} 之间。")
    return value


def _bounded_float(raw: str, *, label: str, minimum: float, maximum: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{label}必须是数字。") from exc
    if not minimum <= value <= maximum:
        raise _invalid(f"{label}必须在 {minimum:g}–{maximum:g} 之间。")
    return value


def _validated_recognition(form: RecognitionSettingsForm) -> RecognitionSettingsProjection:
    provider = form.ocr_provider.strip().lower()
    fallback = form.ocr_fallback_provider.strip().lower()
    debt_provider = form.debt_bill_provider.strip().lower()
    if provider not in {"empty", "rapidocr", "local_llm"}:
        raise _invalid("请选择可用的票据识别方式。")
    if fallback not in {"empty", "rapidocr", "local_llm"}:
        raise _invalid("请选择可用的备用识别方式。")
    if debt_provider not in {"empty", "local_llm"}:
        raise _invalid("请选择可用的债务账单录入方式。")
    rapidocr_available = importlib.util.find_spec("rapidocr") is not None
    if "rapidocr" in {provider, fallback} and not rapidocr_available:
        raise _invalid("这台主机没有安装 RapidOCR，请改用本机视觉模型或手动核对。")
    if fallback != "empty" and fallback == provider:
        raise _invalid("备用识别方式不能与主要方式相同。")
    if provider == "empty" and form.ocr_auto_run:
        raise _invalid("请先选择票据识别方式，再开启自动识别。")

    timezone_name = form.ocr_default_timezone.strip() or "Asia/Shanghai"
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise _invalid("默认时区无效，请填写 IANA 时区，例如 Asia/Shanghai。") from exc

    raw_base_url = form.local_llm_base_url.strip()
    base_url = resolve_local_llm_base_url(raw_base_url)
    if raw_base_url and not base_url:
        raise _invalid("本机模型地址只允许 127.0.0.1、localhost 或 ::1 的 HTTP(S) 地址。")
    if (provider == "local_llm" or fallback == "local_llm" or debt_provider == "local_llm") and not base_url:
        raise _invalid("使用本机视觉模型前，请先填写本机模型地址。")

    model = form.local_llm_model.strip()
    if len(model.encode("utf-8")) > 256:
        raise _invalid("模型名称过长。")
    return RecognitionSettingsProjection(
        ocr_provider=provider,
        ocr_auto_run=form.ocr_auto_run,
        ocr_fallback_provider=fallback,
        ocr_min_confidence=_bounded_float(
            form.ocr_min_confidence,
            label="备用识别阈值",
            minimum=0,
            maximum=1,
        ),
        ocr_default_timezone=timezone_name,
        local_llm_base_url=base_url,
        local_llm_model=model,
        local_llm_timeout_seconds=_bounded_int(
            form.local_llm_timeout_seconds,
            label="识别超时",
            minimum=5,
            maximum=300,
        ),
        local_llm_max_concurrent=_bounded_int(
            form.local_llm_max_concurrent,
            label="并发任务数",
            minimum=1,
            maximum=8,
        ),
        local_llm_queue_timeout_seconds=_bounded_float(
            form.local_llm_queue_timeout_seconds,
            label="排队等待",
            minimum=0,
            maximum=60,
        ),
        debt_bill_provider=debt_provider,
    )


def update_recognition_settings(form: RecognitionSettingsForm) -> RecognitionSettingsView:
    if "RECOGNITION_PIPELINE" not in _EDITABLE_KEYS:
        raise AppError("invalid_request", "该配置项不允许在 Owner Console 中修改。", status_code=403)
    recognition = _validated_recognition(form)
    settings = get_settings()
    patch_runtime_settings(
        _SETTINGS_PATH,
        defaults=RuntimeSettingsProjection(
            public_base_url=settings.public_base_url,
            budget_advisor_owner_confirmed=settings.budget_advisor_owner_confirmed,
        ),
        mutation=RuntimeSettingsMutation(field="recognition", value=recognition),
        service_owned=_SERVICE_OWNED,
    )
    get_settings.cache_clear()  # type: ignore[attr-defined]
    return get_recognition_view()


def update_public_base_url(raw: str) -> RuntimeSettingsView:
    if "PUBLIC_BASE_URL" not in _EDITABLE_KEYS:
        raise AppError("invalid_request", "该配置项不允许在 Owner Console 中修改。", status_code=403)
    value = _validate_public_base_url(raw)
    _write_runtime_value("PUBLIC_BASE_URL", value)
    return get_view()


def update_budget_advisor_owner_confirmed(confirmed: bool) -> bool:
    value = "true" if confirmed else "false"
    projection = _write_runtime_value("BUDGET_ADVISOR_OWNER_CONFIRMED", value)
    return projection.budget_advisor_owner_confirmed
