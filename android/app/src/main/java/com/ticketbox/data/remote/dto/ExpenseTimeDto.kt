package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ExpenseAccountingTimeDto(
    val precision: String,
    @param:Json(name = "instant_utc") val instantUtc: String? = null,
    @param:Json(name = "user_local_date") val userLocalDate: String? = null,
    @param:Json(name = "source_timezone") val sourceTimezone: String? = null,
    @param:Json(name = "source_utc_offset_seconds") val sourceUtcOffsetSeconds: Int? = null,
    @param:Json(name = "accounting_date") val accountingDate: String? = null,
    @param:Json(name = "calendar_revision") val calendarRevision: Long? = null,
    val basis: String? = null,
)

@JsonClass(generateAdapter = true)
data class ExpenseTimeInputDto(
    val precision: String,
    @param:Json(name = "calendar_revision") val calendarRevision: Long,
    @param:Json(name = "user_local_date") val userLocalDate: String,
    @param:Json(name = "instant_utc") val instantUtc: String? = null,
    @param:Json(name = "source_timezone") val sourceTimezone: String? = null,
    @param:Json(name = "source_utc_offset_seconds") val sourceUtcOffsetSeconds: Int? = null,
    @param:Json(name = "accounting_date") val accountingDate: String? = null,
)
