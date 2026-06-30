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
    // ADR-0054: merchant catalog rename/merge blockers use the same flat error
    // envelope contract. A key-changing rename collision carries the colliding
    // catalog row's fresh identity so the UI can steer source -> target merge.
    @param:Json(name = "conflict_merchant_public_id") val conflictMerchantPublicId: String? = null,
    @param:Json(name = "conflict_merchant_row_version") val conflictMerchantRowVersion: Long? = null,
    @param:Json(name = "conflict_merchant_display_name") val conflictMerchantDisplayName: String? = null,
    @param:Json(name = "conflict_merchant_status") val conflictMerchantStatus: String? = null,
    @param:Json(name = "conflict_merchant_deleted") val conflictMerchantDeleted: Boolean? = null,
    // ADR-0054: alias_policy=create_source_alias can be blocked by an existing
    // alias row with the source key; keep its fresh token for actionable copy.
    @param:Json(name = "conflict_alias_public_id") val conflictAliasPublicId: String? = null,
    @param:Json(name = "conflict_alias_row_version") val conflictAliasRowVersion: Long? = null,
    @param:Json(name = "conflict_alias_enabled") val conflictAliasEnabled: Boolean? = null,
    @param:Json(name = "conflict_alias_deleted") val conflictAliasDeleted: Boolean? = null,
)
