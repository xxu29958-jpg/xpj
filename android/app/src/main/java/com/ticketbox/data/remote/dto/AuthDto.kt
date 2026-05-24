package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class AuthCheckDto(
    val status: String,
    @param:Json(name = "account_name")
    val accountName: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    @param:Json(name = "ledger_name")
    val ledgerName: String,
    @param:Json(name = "device_name")
    val deviceName: String,
    val role: String,
    val scope: String,
)

data class PairRequestDto(
    @param:Json(name = "pairing_code")
    val pairingCode: String,
    @param:Json(name = "device_name")
    val deviceName: String,
    val platform: String,
)

data class PairResponseDto(
    @param:Json(name = "session_token")
    val sessionToken: String,
    @param:Json(name = "account_name")
    val accountName: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    @param:Json(name = "ledger_name")
    val ledgerName: String,
    @param:Json(name = "device_name")
    val deviceName: String,
    val role: String,
    @param:Json(name = "expires_at")
    val expiresAt: String? = null,
    @param:Json(name = "soft_refresh_after")
    val softRefreshAfter: String? = null,
)

data class RefreshSessionResponseDto(
    @param:Json(name = "session_token")
    val sessionToken: String,
    @param:Json(name = "expires_at")
    val expiresAt: String?,
    @param:Json(name = "soft_refresh_after")
    val softRefreshAfter: String?,
    val rotated: Boolean,
)

data class StatusDto(
    val status: String,
)

data class ServerSettingsDto(
    @param:Json(name = "account_name")
    val accountName: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String? = null,
    @param:Json(name = "ledger_name")
    val ledgerName: String,
    @param:Json(name = "ledger_is_default")
    val ledgerIsDefault: Boolean? = null,
    @param:Json(name = "device_name")
    val deviceName: String,
    val role: String,
    val status: String,
    @param:Json(name = "storage_status")
    val storageStatus: String,
    @param:Json(name = "pending_count")
    val pendingCount: Int,
    @param:Json(name = "confirmed_count")
    val confirmedCount: Int,
    @param:Json(name = "rejected_count")
    val rejectedCount: Int,
    @param:Json(name = "suspected_duplicate_count")
    val suspectedDuplicateCount: Int,
    @param:Json(name = "upload_storage_bytes")
    val uploadStorageBytes: Long,
    @param:Json(name = "latest_upload_at")
    val latestUploadAt: String?,
)
