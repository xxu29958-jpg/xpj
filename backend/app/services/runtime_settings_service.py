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

from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import BACKEND_ROOT, DATA_ROOT, get_settings, runtime_settings_service_owned
from app.errors import AppError
from app.services.runtime_settings_store import (
    RuntimeSettingsMutation,
    RuntimeSettingsProjection,
    patch_runtime_settings,
)
from app.version import BACKEND_VERSION

_SETTINGS_PATH = DATA_ROOT / "runtime-settings" / "runtime-settings.json"
_SERVICE_OWNED = runtime_settings_service_owned()

_EDITABLE_KEYS: frozenset[str] = frozenset({"BUDGET_ADVISOR_OWNER_CONFIRMED", "PUBLIC_BASE_URL"})


@dataclass(frozen=True)
class RuntimeSettingsView:
    public_base_url: str
    public_base_url_configured: bool
    settings_path: str
    settings_exists: bool


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
