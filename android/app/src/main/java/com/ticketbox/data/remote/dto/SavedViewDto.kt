package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.ticketbox.domain.model.SavedView

data class SavedViewListDto(val items: List<SavedView>)

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
