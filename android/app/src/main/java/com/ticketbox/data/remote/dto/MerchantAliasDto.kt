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
