"""Windows Credential Manager storage for the Desktop rebind recovery record.

Desktop pairing and ledger-switch are two-phase ceremonies: the Manager
first stages a client-generated activation attempt proof, then promotes it
through the backend ``/api/auth/desktop/activate`` endpoint. A process death
between the phases must not lose that proof — it is the only way to replay
the committed activation (the staged credential's value is derived from it,
never server-minted). The record is scoped to one Ticketbox installation by
a non-sensitive target name; secret material never appears in ``repr``.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
from dataclasses import dataclass, field
from typing import Final

from backend_manager.product_identity import (
    ProductCredentialError,
    _CredentialW,
    _wincred,
)

_CRED_TYPE_GENERIC: Final = 1
_ERROR_NOT_FOUND: Final = 1168
_MAX_RECOVERY_BYTES: Final = 5 * 1024
_SCHEMA_VERSION: Final = 1


@dataclass(frozen=True)
class RebindRecovery:
    """The durable half of one in-flight two-phase credential ceremony."""

    activation_attempt_id: str
    activation_attempt_secret: str = field(repr=False)
    account_name: str = ""
    ledger_id: str = ""
    ledger_name: str = ""
    device_name: str = ""
    role: str = ""
    activation_expires_at: str | None = None
    # Cross-ledger credential this ceremony replaces; owed a client-side
    # revoke after promotion. Optional so v1 records decode unchanged.
    superseded_session_token: str | None = field(default=None, repr=False)


def recovery_target(installation_id: str) -> str:
    """Return a non-sensitive, fixed-size WinCred target for one installation."""

    normalized = installation_id.strip()
    if not normalized:
        raise ProductCredentialError("桌面身份缺少安装标识，已停止读取恢复记录。")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return f"Ticketbox/DesktopRebindRecovery/{digest}"


def _encode_recovery(recovery: RebindRecovery) -> bytes:
    payload = {
        "version": _SCHEMA_VERSION,
        "activation_attempt_id": recovery.activation_attempt_id,
        "activation_attempt_secret": recovery.activation_attempt_secret,
        "account_name": recovery.account_name,
        "ledger_id": recovery.ledger_id,
        "ledger_name": recovery.ledger_name,
        "device_name": recovery.device_name,
        "role": recovery.role,
        "activation_expires_at": recovery.activation_expires_at,
        "superseded_session_token": recovery.superseded_session_token,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_RECOVERY_BYTES:
        raise ProductCredentialError("桌面身份恢复记录超过 Windows 安全存储上限。")
    return encoded


def _required_text(payload: dict, key: str, *, max_length: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ProductCredentialError("Windows 安全存储中的桌面身份恢复记录无效。")
    return value


def _metadata_text(payload: dict, key: str, *, max_length: int) -> str:
    """Metadata field that may be empty while a pair attempt is provisional."""
    value = payload.get(key)
    if not isinstance(value, str) or len(value) > max_length:
        raise ProductCredentialError("Windows 安全存储中的桌面身份恢复记录无效。")
    return value


def _decode_recovery(raw: bytes) -> RebindRecovery:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductCredentialError("Windows 安全存储中的桌面身份恢复记录无法读取。") from exc
    if not isinstance(payload, dict) or payload.get("version") != _SCHEMA_VERSION:
        raise ProductCredentialError("Windows 安全存储中的桌面身份恢复记录版本不受支持。")
    activation_expires_at = payload.get("activation_expires_at")
    if activation_expires_at is not None and (
        not isinstance(activation_expires_at, str) or len(activation_expires_at) > 64
    ):
        raise ProductCredentialError("Windows 安全存储中的桌面身份恢复记录无效。")
    superseded_session_token = payload.get("superseded_session_token")
    if superseded_session_token is not None and (
        not isinstance(superseded_session_token, str) or len(superseded_session_token) > 512
    ):
        raise ProductCredentialError("Windows 安全存储中的桌面身份恢复记录无效。")
    return RebindRecovery(
        activation_attempt_id=_required_text(payload, "activation_attempt_id", max_length=64),
        activation_attempt_secret=_required_text(payload, "activation_attempt_secret", max_length=128),
        account_name=_metadata_text(payload, "account_name", max_length=120),
        ledger_id=_metadata_text(payload, "ledger_id", max_length=64),
        ledger_name=_metadata_text(payload, "ledger_name", max_length=120),
        device_name=_metadata_text(payload, "device_name", max_length=120),
        role=_metadata_text(payload, "role", max_length=32),
        activation_expires_at=activation_expires_at,
        superseded_session_token=superseded_session_token,
    )


def save_rebind_recovery(installation_id: str, recovery: RebindRecovery) -> None:
    raw = _encode_recovery(recovery)
    blob = ctypes.create_string_buffer(raw)
    credential = _CredentialW(
        Flags=0,
        Type=_CRED_TYPE_GENERIC,
        TargetName=recovery_target(installation_id),
        Comment="Ticketbox Desktop rebind recovery",
        CredentialBlobSize=len(raw),
        CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte)),
        Persist=2,  # CRED_PERSIST_LOCAL_MACHINE
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


def load_rebind_recovery(installation_id: str) -> RebindRecovery | None:
    library = _wincred()
    pointer = ctypes.POINTER(_CredentialW)()
    if not library.CredReadW(
        recovery_target(installation_id),
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
            or credential.CredentialBlobSize > _MAX_RECOVERY_BYTES
        ):
            raise ProductCredentialError("Windows 安全存储中的桌面身份恢复记录大小无效。")
        raw = ctypes.string_at(
            credential.CredentialBlob,
            credential.CredentialBlobSize,
        )
        return _decode_recovery(raw)
    finally:
        library.CredFree(pointer)


def delete_rebind_recovery(installation_id: str) -> None:
    library = _wincred()
    if library.CredDeleteW(
        recovery_target(installation_id),
        _CRED_TYPE_GENERIC,
        0,
    ):
        return
    error_code = ctypes.get_last_error()
    if error_code != _ERROR_NOT_FOUND:
        raise ProductCredentialError(
            f"无法清除 Windows 凭据管理器（错误 {error_code}）。"
        )
