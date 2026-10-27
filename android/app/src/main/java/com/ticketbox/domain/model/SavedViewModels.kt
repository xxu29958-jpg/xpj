package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class SavedViewDefinitionRequest(
    val name: String,
    val monthMode: String,
    val month: String?,
    val filter: String,
    val tagPublicId: String?,
    val homeCurrencyCode: String,
    val queryText: String,
    val category: String,
)

data class SavedViewDeletionReceipt(
    val publicId: String,
    val rowVersion: Long,
    val name: String,
)

data class SavedView(
    val publicId: String,
    val name: String,
    val rowVersion: Long,
    val monthMode: String,
    val month: String?,
    val filter: String,
    val tagPublicId: String?,
    val tagName: String?,
    val homeCurrencyCode: String,
    val repairReason: String?,
    val queryText: String,
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
