package com.ticketbox.domain.model

import com.squareup.moshi.JsonClass

/** Server-owned time evidence; absent legacy evidence is never inferred from a display timestamp. */
@JsonClass(generateAdapter = true)
data class ExpenseAccountingTime(
    val precision: String,
    val instantUtc: String? = null,
    val userLocalDate: String? = null,
    val sourceTimezone: String? = null,
    val sourceUtcOffsetSeconds: Int? = null,
    val accountingDate: String? = null,
    val calendarRevision: Long? = null,
    val basis: String? = null,
)

/** The original user selection, captured once before the existing outbox accepts the command. */
data class ExpenseTimeInput(
    val precision: String,
    val calendarRevision: Long,
    val userLocalDate: String,
    val instantUtc: String? = null,
    val sourceTimezone: String? = null,
    val sourceUtcOffsetSeconds: Int? = null,
    val accountingDate: String? = null,
)
