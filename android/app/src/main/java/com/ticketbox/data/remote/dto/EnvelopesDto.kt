package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class EnvelopeSnapshotDto(
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "account_public_ids") val accountPublicIds: List<String>,
    val allocations: Map<String, Long>)

@JsonClass(generateAdapter = true)
data class EnvelopeRevisionDto(
    @param:Json(name = "row_version") val rowVersion: Long, val month: String, val reason: String,
    @param:Json(name = "recorded_at") val recordedAt: String,
    @param:Json(name = "allocation_snapshot") val allocationSnapshot: EnvelopeSnapshotDto)

@JsonClass(generateAdapter = true)
data class EnvelopeSaveDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "account_public_ids") val accountPublicIds: List<String>,
    @param:Json(name = "account_row_versions") val accountRowVersions: Map<String, Long>,
    val allocations: Map<String, Long>, val reason: String,
)

@JsonClass(generateAdapter = true)
data class EnvelopeAccountDto(val name: String,
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "balance_minor") val balanceMinor: Long?,
    @param:Json(name = "row_version") val rowVersion: Long,
    val selected: Boolean, @param:Json(name = "can_select") val canSelect: Boolean)

@JsonClass(generateAdapter = true)
data class EnvelopePurposeDto(val purpose: String, val label: String, val funded: Boolean,
    @param:Json(name = "planned_minor") val plannedMinor: Long?,
    @param:Json(name = "allocated_minor") val allocatedMinor: Long,
    @param:Json(name = "spent_minor") val spentMinor: Long?,
    @param:Json(name = "unpaid_credit_minor") val unpaidCreditMinor: Long?,
    @param:Json(name = "unlinked_minor") val unlinkedMinor: Long?,
    @param:Json(name = "available_minor") val availableMinor: Long?,
    @param:Json(name = "reserved_minor") val reservedMinor: Long?)

@JsonClass(generateAdapter = true)
data class EnvelopeMonthDto(val month: String,
    @param:Json(name = "reserved_minor") val reservedMinor: Long?)

@JsonClass(generateAdapter = true)
data class EnvelopesDto(
    @param:Json(name = "ledger_id") val ledgerId: String, val month: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "read_at") val readAt: String,
    @param:Json(name = "valuation_date") val valuationDate: String,
    @param:Json(name = "cash_minor") val cashMinor: Long?,
    @param:Json(name = "reserved_minor") val reservedMinor: Long?,
    @param:Json(name = "unassigned_minor") val unassignedMinor: Long?,
    val accounts: List<EnvelopeAccountDto>, val purposes: List<EnvelopePurposeDto>,
    val months: List<EnvelopeMonthDto>, val notices: List<String>,
)
