package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * issue #65 slice 6b: owner "My Devices" DTOs for the
 * ``/api/ledgers/{ledger_id}/devices`` routes (backend slice 6a). Field names
 * match the backend ``MyDeviceResponse`` / ``PairingCodeResponse`` schemas; the
 * rename body reuses the backend ``AdminDeviceRenameRequest`` shape.
 */
data class MyDeviceDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "device_name")
    val deviceName: String,
    val platform: String,
    @param:Json(name = "last_seen_at")
    val lastSeenAt: String? = null,
    @param:Json(name = "created_at")
    val createdAt: String? = null,
    @param:Json(name = "revoked_at")
    val revokedAt: String? = null,
    @param:Json(name = "is_current")
    val isCurrent: Boolean,
)

data class MyDeviceListResponseDto(
    val devices: List<MyDeviceDto>,
)

data class DeviceRenameRequestDto(
    @param:Json(name = "device_name")
    val deviceName: String,
)

data class PairingCodeCreateRequestDto(
    @param:Json(name = "device_name_hint")
    val deviceNameHint: String? = null,
    @param:Json(name = "ttl_minutes")
    val ttlMinutes: Int = 15,
)

data class PairingCodeResponseDto(
    @param:Json(name = "pairing_code")
    val pairingCode: String,
    @param:Json(name = "ledger_name")
    val ledgerName: String,
    @param:Json(name = "expires_at")
    val expiresAt: String,
)
