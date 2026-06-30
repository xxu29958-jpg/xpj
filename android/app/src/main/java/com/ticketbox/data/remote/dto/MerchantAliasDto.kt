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

data class MerchantCatalogDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "display_name")
    val displayName: String,
    @param:Json(name = "merchant_key")
    val merchantKey: String,
    val status: String,
    @param:Json(name = "merged_into_public_id")
    val mergedIntoPublicId: String? = null,
    @param:Json(name = "usage_count")
    val usageCount: Int,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "row_version")
    val rowVersion: Long,
    @param:Json(name = "deleted_at")
    val deletedAt: String? = null,
)

data class MerchantCatalogListDto(
    val items: List<MerchantCatalogDto>,
)

data class MerchantCatalogCreateRequest(
    @param:Json(name = "display_name")
    val displayName: String,
    val status: String = "active",
)

data class MerchantCatalogUpdateRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    @param:Json(name = "display_name")
    val displayName: String? = null,
    val status: String? = null,
)

data class MerchantCatalogDeleteRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

data class MerchantCatalogMergeRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    @param:Json(name = "target_public_id")
    val targetPublicId: String,
    @param:Json(name = "target_row_version")
    val targetRowVersion: Long,
    @param:Json(name = "alias_policy")
    val aliasPolicy: String,
    @param:Json(name = "rewrite_historical_expenses")
    val rewriteHistoricalExpenses: Boolean = false,
)

data class MerchantCatalogMergeDto(
    val source: MerchantCatalogDto,
    val target: MerchantCatalogDto,
    @param:Json(name = "created_alias_public_id")
    val createdAliasPublicId: String? = null,
)
