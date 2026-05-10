package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * v0.4-alpha1 multi-ledger DTOs.
 *
 * The mobile app receives [LedgerDto] entries and never deals with the
 * server-side numeric primary key — it identifies a ledger purely by its
 * public [ledgerId] string. Ownership is decided server-side; the client
 * only renders [role] for read-only display.
 */
data class LedgerDto(
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    val name: String,
    val role: String,
    @param:Json(name = "is_default")
    val isDefault: Boolean,
    @param:Json(name = "created_at")
    val createdAt: String?,
    @param:Json(name = "archived_at")
    val archivedAt: String?,
)

data class LedgerListResponseDto(
    val ledgers: List<LedgerDto>,
)

data class LedgerCreateRequestDto(
    val name: String,
)

data class LedgerSwitchResponseDto(
    @param:Json(name = "session_token")
    val sessionToken: String,
    val ledger: LedgerDto,
    @param:Json(name = "account_name")
    val accountName: String,
    @param:Json(name = "device_name")
    val deviceName: String,
)
