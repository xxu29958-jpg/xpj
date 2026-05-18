"""Owner Console — runtime settings backed by ``backend/.env``.

Lets the operator change a small set of operator-friendly settings from the
Owner Console (currently just :envvar:`PUBLIC_BASE_URL`) without dropping
into a text editor. The .env file is rewritten in-place and
:func:`app.config.get_settings` cache is invalidated so subsequent requests
see the new value immediately.

Security:
- Only callable from Owner Console routes (loopback-only).
- The .env file lives outside the web root and is never served.
- We only allow keys whitelisted in :data:`_EDITABLE_KEYS`.
- Values are validated before being written.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import BACKEND_ROOT, get_settings
from app.errors import AppError
from app.version import BACKEND_VERSION


_ENV_PATH = BACKEND_ROOT / ".env"

_EDITABLE_KEYS: frozenset[str] = frozenset({"PUBLIC_BASE_URL"})


@dataclass(frozen=True)
class RuntimeSettingsView:
    public_base_url: str
    public_base_url_configured: bool
    env_path: str
    env_exists: bool


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
        env_path=str(_ENV_PATH),
        env_exists=_ENV_PATH.is_file(),
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


def _validate_public_base_url(raw: str) -> str:
    """Validate and normalise PUBLIC_BASE_URL.

    Only an *origin* (scheme + host + optional port) is accepted. Paths,
    query strings and fragments are rejected to prevent accidental
    misconfiguration that would produce malformed upload URLs.

    Allowed:   https://api.example.com   http://127.0.0.1:8000
    Rejected:  https://api.example.com/  https://api.example.com/foo
               https://api.example.com?x=1  https://api.example.com#abc
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
            "公网域名必须包含主机名，例如 https://api.example.com。",
            status_code=422,
        )
    if parsed.path.rstrip("/"):
        raise AppError(
            "invalid_request",
            "公网域名只能填写域名根（不允许带路径），例如 https://api.example.com。",
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


def _read_env_lines() -> list[str]:
    if not _ENV_PATH.is_file():
        return []
    return _ENV_PATH.read_text(encoding="utf-8-sig").splitlines()


def _write_env_lines(lines: list[str]) -> None:
    _ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines).rstrip("\n") + "\n"
    _ENV_PATH.write_text(text, encoding="utf-8")


def _set_env_key(lines: list[str], key: str, value: str) -> list[str]:
    """Replace ``KEY=...`` in-place; append at end if absent.

    Lines starting with ``# KEY=`` (commented examples) are left intact.
    """
    new_line = f"{key}={value}"
    out: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            out.append(line)
            continue
        head = line.split("=", 1)[0].strip()
        if head == key:
            if not replaced:
                out.append(new_line)
                replaced = True
            # drop duplicates
            continue
        out.append(line)
    if not replaced:
        out.append(new_line)
    return out


def update_public_base_url(raw: str) -> RuntimeSettingsView:
    if "PUBLIC_BASE_URL" not in _EDITABLE_KEYS:
        raise AppError("invalid_request", "该配置项不允许在 Owner Console 中修改。", status_code=403)
    value = _validate_public_base_url(raw)
    lines = _read_env_lines()
    lines = _set_env_key(lines, "PUBLIC_BASE_URL", value)
    _write_env_lines(lines)

    # Invalidate cached Settings and re-import os.environ so the change is
    # visible to subsequent requests in the same process.
    import os

    os.environ["PUBLIC_BASE_URL"] = value
    get_settings.cache_clear()  # type: ignore[attr-defined]
    return get_view()
