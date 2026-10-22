package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.ticketbox.notification.NotificationTimeEvidence

@JsonClass(generateAdapter = true)
data class NotificationTimeFragmentDto(val field: String, val literal: String, val label: String)

@JsonClass(generateAdapter = true)
data class NotificationTimeEvidenceDto(
    @param:Json(name = "source_timezone") val sourceTimezone: String?,
    val fragments: List<NotificationTimeFragmentDto>, val truncated: Boolean,
)

internal fun NotificationTimeEvidence.toDto() = NotificationTimeEvidenceDto(sourceTimezone,
    fragments.map { NotificationTimeFragmentDto(it.field, it.literal, it.label) }, truncated)
