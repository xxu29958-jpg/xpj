package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class MerchantAliasDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "canonical_merchant")
    val canonicalMerchant: String,
    @param:Json(name = "canonical_key")
    val canonicalKey: String,
    val alias: String,
    @param:Json(name = "alias_key")
    val aliasKey: String,
    val enabled: Boolean,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "row_version")
    val rowVersion: Long,
)

data class MerchantAliasListDto(
    val items: List<MerchantAliasDto>,
)

data class MerchantAliasRequest(
    @param:Json(name = "canonical_merchant")
    val canonicalMerchant: String? = null,
    val alias: String? = null,
    val enabled: Boolean? = null,
)

/**
 * ADR-0038 PR-2e: PATCH /api/merchants/aliases/{publicId} body.
 *
 * Carries the optimistic-concurrency token alongside the partial
 * update payload — server requires it.
 */
data class MerchantAliasUpdateRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    @param:Json(name = "canonical_merchant")
    val canonicalMerchant: String? = null,
    val alias: String? = null,
    val enabled: Boolean? = null,
)

/**
 * ADR-0038 PR-2e: DELETE /api/merchants/aliases/{publicId} body.
 *
 * Mirrors CategoryRuleDeleteRequest — DELETE carries a body so the
 * token travels through the same channel as PATCH.
 */
data class MerchantAliasDeleteRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)
