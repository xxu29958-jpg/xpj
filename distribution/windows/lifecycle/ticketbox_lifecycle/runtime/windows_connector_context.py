"""Independent elevated admission to the Backend-owned public-origin revision."""

from __future__ import annotations

import json
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.connector_profile import SERVICE_NAME
from ticketbox_lifecycle.runtime import windows_security_native as native


def public_origin_revision(data_root: Path, backend_sid: str) -> int:
    path = data_root / "app" / "runtime-settings" / "runtime-settings.json"
    native.reject_reparse_components(path)
    if not path.exists():
        raise LifecycleError("connector_origin_unavailable", "set the public address through the local Owner session first")
    expected = native._canonical_dacl_sddl(f"D:P(A;;FA;;;{backend_sid})(A;;FA;;;SY)(A;;FA;;;BA)")
    for stage in ("before", "after"):
        native.reject_reparse_components(path)
        if native.file_owner_sid(path) != backend_sid or native._object_dacl_sddl(path) != expected:
            raise LifecycleViolation("connector_origin_untrusted", "public origin projection is not Backend-owned")
        if stage == "before":
            with path.open("rb") as stream:
                raw = stream.read(32769)
    if len(raw) > 32768:
        raise LifecycleError("connector_origin_invalid", "public origin projection exceeds its fixed limit")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise LifecycleError("connector_origin_invalid", "public origin projection is unreadable") from None
    if not isinstance(payload, dict) or payload.get("schema") != "ticketbox-runtime-settings-v5":
        raise LifecycleError("connector_origin_invalid", "a current public origin revision is required")
    if not isinstance(payload.get("public_base_url"), str) or not payload["public_base_url"].startswith("https://"):
        raise LifecycleError("connector_origin_unavailable", "set a confirmed public address through the local Owner session first")
    revision = payload.get("public_origin_revision")
    if type(revision) is not int or not 0 <= revision < 2**53:
        raise LifecycleError("connector_origin_invalid", "public origin revision is invalid")
    return revision


def require_no_environment_overrides() -> None:
    import winreg

    # SCM inherits the machine environment, not the Manager's environment.
    path = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
        for index in range(winreg.QueryInfoKey(key)[1]):
            name, _value, _kind = winreg.EnumValue(key, index)
            upper = name.upper()
            if upper.startswith(("TUNNEL_", "CLOUDFLARED_")) or upper in {
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR",
            }:
                raise LifecycleViolation("connector_environment_override", "machine environment overrides the fixed connector profile")
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}")
    except FileNotFoundError:
        return
    with key:
        try:
            winreg.QueryValueEx(key, "Environment")
        except FileNotFoundError:
            return
    raise LifecycleViolation("connector_environment_override", "service environment overrides the fixed connector profile")
