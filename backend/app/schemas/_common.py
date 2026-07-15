"""Top-level health, error, and auth-check envelopes used across surfaces."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "AuthCheckResponse",
    "ErrorResponse",
    "HealthResponse",
    "InstallationHealthResponse",
    "InstallationMobileCapabilitiesResponse",
    "StatusResponse",
]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    error: str
    message: str
    request_id: str | None = None
    conflict_tag_public_id: str | None = None
    conflict_tag_row_version: int | None = None
    conflict_merchant_public_id: str | None = None
    conflict_merchant_row_version: int | None = None
    conflict_merchant_display_name: str | None = None
    conflict_merchant_status: str | None = None
    conflict_merchant_deleted: bool | None = None
    conflict_alias_public_id: str | None = None
    conflict_alias_row_version: int | None = None
    conflict_alias_enabled: bool | None = None
    conflict_alias_deleted: bool | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    backend_version: str | None = None
    identity_schema: str | None = None
    database_status: str | None = None
    upload_dir_status: str | None = None
    owner_console_status: str | None = None
    # 备份链健康(轴6 备份超龄通知的数据源;复用 owner dashboard 的
    # backup_service.backup_health(),48h stale 阈值留在服务端单源,客户端只消费
    # backup_stale 不自带阈值)。latest_backup_at 为 ISO 8601 UTC;无备份时三者
    # 分别为 None / None / True。
    latest_backup_at: str | None = None
    backup_age_hours: int | None = None
    backup_stale: bool | None = None


class InstallationMobileCapabilitiesResponse(BaseModel):
    mobile_endpoint_state: Literal["local_only", "public_configured_unverified"]
    android_binding_state: Literal["setup_required", "configured_unverified"]
    iphone_upload_state: Literal["setup_required", "configured_unverified"]


class InstallationHealthResponse(BaseModel):
    contract: Literal["ticketbox-installation-health-v2"] = "ticketbox-installation-health-v2"
    status: Literal["ok"] = "ok"
    product: Literal["ticketbox"] = "ticketbox"
    backend_version: str
    installation_id: str
    runtime_access_state: Literal["available", "repair_required"]
    owner_state: Literal["configured", "recovery_required"]
    owner_recovery_channel: Literal["development", "managed_host", "operator"]
    mobile_connectivity: InstallationMobileCapabilitiesResponse


class AuthCheckResponse(BaseModel):
    status: str = "ok"
    server_id: str
    data_generation: str
    account_public_id: str
    device_public_id: str
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str
    scope: str


class StatusResponse(BaseModel):
    status: str = "ok"
