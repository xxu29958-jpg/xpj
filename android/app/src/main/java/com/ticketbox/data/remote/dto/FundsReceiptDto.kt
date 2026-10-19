package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/** Outbox acceptance is separate from the ordinary account/envelope read cache. */
@JsonClass(generateAdapter = true)
data class FinancialAccountReceiptDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "ledger_id") val ledgerId: String,
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "balance_minor") val balanceMinor: Long?,
    @param:Json(name = "recorded_change_minor") val recordedChangeMinor: Long,
    // Revision 0 accepts old server responses while discarding their read history.
    @param:Json(name = "receipt_revision") val receiptRevision: Int = 0,
)

@JsonClass(generateAdapter = true)
data class EnvelopeReceiptDto(
    @param:Json(name = "ledger_id") val ledgerId: String,
    val month: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "cash_minor") val cashMinor: Long?,
    @param:Json(name = "reserved_minor") val reservedMinor: Long?,
    @param:Json(name = "unassigned_minor") val unassignedMinor: Long?,
    @param:Json(name = "receipt_revision") val receiptRevision: Int = 0,
)
