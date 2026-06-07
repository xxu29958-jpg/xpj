package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class ErrorDto(
    val error: String,
    val message: String,
    // ADR-0043 契约 5: on a `tag_conflict` the backend flattens the colliding tag's
    // identity onto the error envelope's TOP level (AppError.details →
    // content.setdefault in backend errors.py — NOT a nested object), so the client
    // can steer a rename into a merge against the FRESH server token. Null for every
    // other error.
    @param:Json(name = "conflict_tag_public_id") val conflictTagPublicId: String? = null,
    @param:Json(name = "conflict_tag_row_version") val conflictTagRowVersion: Long? = null,
)
