package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

enum class ConfirmedStreamEntryKindDto(val wireValue: String) {
    @Json(name = "expense")
    Expense("expense"),

    @Json(name = "offset")
    Offset("offset"),
}

enum class ExpenseLineageStatusDto(val wireValue: String) {
    @Json(name = "confirmed")
    Confirmed("confirmed"),

    @Json(name = "partially_refunded")
    PartiallyRefunded("partially_refunded"),

    @Json(name = "fully_refunded")
    FullyRefunded("fully_refunded"),

    @Json(name = "reversed")
    Reversed("reversed");

    companion object {
        fun fromWire(value: String?): ExpenseLineageStatusDto? = entries.firstOrNull { it.wireValue == value }
    }
}

enum class ExpenseOffsetKindDto(val wireValue: String) {
    @Json(name = "refund")
    Refund("refund"),

    @Json(name = "chargeback")
    Chargeback("chargeback"),

    @Json(name = "reversal")
    Reversal("reversal");

    companion object {
        fun fromWire(value: String?): ExpenseOffsetKindDto? = entries.firstOrNull { it.wireValue == value }
    }
}

enum class ExpenseOffsetStatusDto(val wireValue: String) {
    @Json(name = "active")
    Active("active"),

    @Json(name = "voided")
    Voided("voided"),
}

enum class ExpenseRelationshipReasonDto(val wireValue: String) {
    @Json(name = "source_refunded")
    SourceRefunded("source_refunded"),

    @Json(name = "source_chargeback")
    SourceChargeback("source_chargeback"),

    @Json(name = "source_reversed")
    SourceReversed("source_reversed"),
}

enum class ExpenseOffsetChangeKindDto(val wireValue: String) {
    @Json(name = "created")
    Created("created"),

    @Json(name = "correction")
    Correction("correction"),

    @Json(name = "void")
    Void("void"),
}
