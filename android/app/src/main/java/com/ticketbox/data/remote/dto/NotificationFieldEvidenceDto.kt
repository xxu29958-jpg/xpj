package com.ticketbox.data.remote.dto

import com.squareup.moshi.JsonClass
import com.ticketbox.notification.NotificationFieldEvidence

@JsonClass(generateAdapter = true)
data class NotificationFieldFragmentDto(val field: String, val literal: String)

@JsonClass(generateAdapter = true)
data class NotificationFieldEvidenceDto(val fragments: List<NotificationFieldFragmentDto>, val truncated: Boolean = false)

fun NotificationFieldEvidence.toDto() = NotificationFieldEvidenceDto(
    fragments.map { NotificationFieldFragmentDto(it.field, it.literal) }, truncated)
