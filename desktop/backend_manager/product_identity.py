"""Windows Credential Manager storage for the Desktop app principal.

The credential is the existing backend ``AuthToken(scope=app)`` issued by the
normal pairing ceremony. It is scoped to the current Windows user by WinCred
and to one Ticketbox installation by a non-sensitive target name. Token
material never appears in ``repr``, argv, environment variables, URLs, or
Manager status payloads.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Final

_CRED_TYPE_GENERIC: Final = 1
_CRED_PERSIST_LOCAL_MACHINE: Final = 2
_ERROR_NOT_FOUND: Final = 1168
_MAX_CREDENTIAL_BYTES: Final = 5 * 1024
_SCHEMA_VERSION: Final = 1


class ProductCredentialError(RuntimeError):
    """Fail-closed WinCred error without credential material."""


@dataclass(frozen=True)
class ProductSession:
    session_token: str = field(repr=False)
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str
    expires_at: str | None

    def public_projection(self) -> dict:
        return {
            "configured": True,
            "account_name": self.account_name,
            "ledger_id": self.ledger_id,
            "ledger_name": self.ledger_name,
            "device_name": self.device_name,
            "role": self.role,
            "expires_at": self.expires_at,
        }


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def credential_target(installation_id: str) -> str:
    """Return a non-sensitive, fixed-size WinCred target for one installation."""

    normalized = installation_id.strip()
    if not normalized:
        raise ProductCredentialError("桌面身份缺少安装标识，已停止读取凭证。")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return f"Ticketbox/DesktopAppSession/{digest}"


def _encode_session(session: ProductSession) -> bytes:
    payload = {
        "version": _SCHEMA_VERSION,
        "session_token": session.session_token,
        "account_name": session.account_name,
        "ledger_id": session.ledger_id,
        "ledger_name": session.ledger_name,
        "device_name": session.device_name,
        "role": session.role,
        "expires_at": session.expires_at,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_CREDENTIAL_BYTES:
        raise ProductCredentialError("桌面身份凭证超过 Windows 安全存储上限。")
    return encoded


def _required_text(payload: dict, key: str, *, max_length: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ProductCredentialError("Windows 安全存储中的桌面身份合同无效。")
    return value


def _decode_session(raw: bytes) -> ProductSession:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductCredentialError("Windows 安全存储中的桌面身份无法读取。") from exc
    if not isinstance(payload, dict) or payload.get("version") != _SCHEMA_VERSION:
        raise ProductCredentialError("Windows 安全存储中的桌面身份版本不受支持。")
    expires_at = payload.get("expires_at")
    if expires_at is not None and (
        not isinstance(expires_at, str) or len(expires_at) > 64
    ):
        raise ProductCredentialError("Windows 安全存储中的桌面身份合同无效。")
    return ProductSession(
        session_token=_required_text(payload, "session_token", max_length=512),
        account_name=_required_text(payload, "account_name", max_length=120),
        ledger_id=_required_text(payload, "ledger_id", max_length=64),
        ledger_name=_required_text(payload, "ledger_name", max_length=120),
        device_name=_required_text(payload, "device_name", max_length=120),
        role=_required_text(payload, "role", max_length=32),
        expires_at=expires_at,
    )


def _wincred():
    if os.name != "nt":
        raise ProductCredentialError("桌面身份安全存储只支持 Windows。")
    library = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    library.CredWriteW.argtypes = [ctypes.POINTER(_CredentialW), wintypes.DWORD]
    library.CredWriteW.restype = wintypes.BOOL
    library.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CredentialW)),
    ]
    library.CredReadW.restype = wintypes.BOOL
    library.CredDeleteW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    library.CredDeleteW.restype = wintypes.BOOL
    library.CredFree.argtypes = [ctypes.c_void_p]
    library.CredFree.restype = None
    return library


def save_product_session(installation_id: str, session: ProductSession) -> None:
    raw = _encode_session(session)
    blob = ctypes.create_string_buffer(raw)
    credential = _CredentialW(
        Flags=0,
        Type=_CRED_TYPE_GENERIC,
        TargetName=credential_target(installation_id),
        Comment="Ticketbox Desktop application session",
        CredentialBlobSize=len(raw),
        CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte)),
        Persist=_CRED_PERSIST_LOCAL_MACHINE,
        AttributeCount=0,
        Attributes=None,
        TargetAlias=None,
        UserName="Ticketbox Desktop",
    )
    if not _wincred().CredWriteW(ctypes.byref(credential), 0):
        error_code = ctypes.get_last_error()
        raise ProductCredentialError(
            f"无法写入 Windows 凭据管理器（错误 {error_code}）。"
        )


def load_product_session(installation_id: str) -> ProductSession | None:
    library = _wincred()
    pointer = ctypes.POINTER(_CredentialW)()
    if not library.CredReadW(
        credential_target(installation_id),
        _CRED_TYPE_GENERIC,
        0,
        ctypes.byref(pointer),
    ):
        error_code = ctypes.get_last_error()
        if error_code == _ERROR_NOT_FOUND:
            return None
        raise ProductCredentialError(
            f"无法读取 Windows 凭据管理器（错误 {error_code}）。"
        )
    try:
        credential = pointer.contents
        if (
            credential.CredentialBlobSize <= 0
            or credential.CredentialBlobSize > _MAX_CREDENTIAL_BYTES
        ):
            raise ProductCredentialError("Windows 安全存储中的桌面身份大小无效。")
        raw = ctypes.string_at(
            credential.CredentialBlob,
            credential.CredentialBlobSize,
        )
        return _decode_session(raw)
    finally:
        library.CredFree(pointer)


def delete_product_session(installation_id: str) -> None:
    library = _wincred()
    if library.CredDeleteW(
        credential_target(installation_id),
        _CRED_TYPE_GENERIC,
        0,
    ):
        return
    error_code = ctypes.get_last_error()
    if error_code != _ERROR_NOT_FOUND:
        raise ProductCredentialError(
            f"无法清除 Windows 凭据管理器（错误 {error_code}）。"
        )
