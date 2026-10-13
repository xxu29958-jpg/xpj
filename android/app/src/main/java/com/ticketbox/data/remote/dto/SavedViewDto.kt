package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

data class SavedViewDto(
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

data class SavedViewListDto(val items: List<SavedViewDto>)

@JsonClass(generateAdapter = true)
data class SavedViewDefinitionRequestDto(
    val name: String,
    @param:Json(name = "month_mode") val monthMode: String,
    val month: String?,
    val filter: String,
    @param:Json(name = "tag_public_id") val tagPublicId: String?,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "query_text") val queryText: String,
    val category: String,
)

@JsonClass(generateAdapter = true)
data class SavedViewUpdateRequestDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    val name: String,
    @param:Json(name = "month_mode") val monthMode: String,
    val month: String?,
    val filter: String,
    @param:Json(name = "tag_public_id") val tagPublicId: String?,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "query_text") val queryText: String,
    val category: String,
)

@JsonClass(generateAdapter = true)
data class SavedViewDeleteRequestDto(@param:Json(name = "expected_row_version") val expectedRowVersion: Long)

data class SavedViewDeletionReceiptDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    val name: String,
)

data class SavedViewResultRowDto(
    val entry: ConfirmedExpenseStreamItemDto,
    @param:Json(name = "projected_amount_cents") val projectedAmountCents: Long?,
    @param:Json(name = "projection_gap") val projectionGap: MissingExchangeRateDto?,
)

data class SavedViewResultsDto(
    val conditions: Map<String, String>,
    val items: List<SavedViewResultRowDto>,
    val page: Int,
    @param:Json(name = "page_size") val pageSize: Int,
    val total: Int,
)
