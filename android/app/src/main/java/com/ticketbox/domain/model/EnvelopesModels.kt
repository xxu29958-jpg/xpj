package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class EnvelopeAccount(val name: String,
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "balance_minor") val balanceMinor: Long?,
    @param:Json(name = "row_version") val rowVersion: Long,
    val selected: Boolean, @param:Json(name = "can_select") val canSelect: Boolean)

@JsonClass(generateAdapter = true)
data class EnvelopeMonth(val month: String,
    @param:Json(name = "reserved_minor") val reservedMinor: Long?)

@JsonClass(generateAdapter = true)
data class EnvelopePurpose(val purpose: String, val label: String, val funded: Boolean,
    @param:Json(name = "planned_minor") val plannedMinor: Long?,
    @param:Json(name = "allocated_minor") val allocatedMinor: Long,
    @param:Json(name = "spent_minor") val spentMinor: Long?,
    @param:Json(name = "unpaid_credit_minor") val unpaidCreditMinor: Long?,
    @param:Json(name = "unlinked_minor") val unlinkedMinor: Long?,
    @param:Json(name = "available_minor") val availableMinor: Long?,
    @param:Json(name = "reserved_minor") val reservedMinor: Long?)

@JsonClass(generateAdapter = true)
data class EnvelopeRevision(
    @param:Json(name = "row_version") val rowVersion: Long, val month: String, val reason: String,
    @param:Json(name = "recorded_at") val recordedAt: String,
    @param:Json(name = "allocation_snapshot") val allocationSnapshot: EnvelopeSnapshot)

@JsonClass(generateAdapter = true)
data class EnvelopeSnapshot(
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "account_public_ids") val accountPublicIds: List<String>,
    val allocations: Map<String, Long>)

@JsonClass(generateAdapter = true)
data class Envelopes(
    @param:Json(name = "ledger_id") val ledgerId: String, val month: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "read_at") val readAt: String,
    @param:Json(name = "valuation_date") val valuationDate: String,
    @param:Json(name = "cash_minor") val cashMinor: Long?,
    @param:Json(name = "reserved_minor") val reservedMinor: Long?,
    @param:Json(name = "unassigned_minor") val unassignedMinor: Long?,
    val accounts: List<EnvelopeAccount>, val purposes: List<EnvelopePurpose>,
    val months: List<EnvelopeMonth>, val notices: List<String>,
)
