package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class SavedViewDefinitionRequest(
    val name: String,
    @param:Json(name = "month_mode") val monthMode: String,
    val month: String?,
    val filter: String,
    @param:Json(name = "tag_public_id") val tagPublicId: String?,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "query_text") val queryText: String,
    val category: String,
)

data class SavedViewDeletionReceipt(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    val name: String,
)

data class SavedView(
    @param:Json(name = "public_id") val publicId: String,
    val name: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "month_mode") val monthMode: String,
    val month: String?,
    val filter: String,
    @param:Json(name = "tag_public_id") val tagPublicId: String?,
    @param:Json(name = "tag_name") val tagName: String?,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "repair_reason") val repairReason: String?,
    @param:Json(name = "query_text") val queryText: String,
    val category: String,
)

data class SavedViewResultRow(
    val entry: ConfirmedStreamItem,
    val projectedAmountCents: Long?,
    val projectionGap: CurrencyProjectionGap?,
)

data class SavedViewResults(
    val conditions: Map<String, String>,
    val items: List<SavedViewResultRow>,
    val page: Int,
    val pageSize: Int,
    val total: Int,
)
