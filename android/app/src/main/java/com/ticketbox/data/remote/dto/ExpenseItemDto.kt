package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class ExpenseItemDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val position: Int,
    val kind: String = "product",
    val name: String,
    @param:Json(name = "quantity_text")
    val quantityText: String?,
    @param:Json(name = "unit_price_cents")
    val unitPriceCents: Long?,
    @param:Json(name = "amount_cents")
    val amountCents: Long?,
    val category: String,
    @param:Json(name = "raw_text")
    val rawText: String?,
    val confidence: Double?,
    @param:Json(name = "is_ocr_draft")
    val isOcrDraft: Boolean,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
)

data class ExpenseItemsResponseDto(
    @param:Json(name = "expense_id")
    val expenseId: Long,
    // ADR-0041: parent expense's post-mutation row_version. Lets the outbox
    // dispatcher cascade the fresh OCC token without a second GET — the replace
    // / acknowledge-mismatch responses are now self-describing.
    @param:Json(name = "row_version")
    val rowVersion: Long,
    @param:Json(name = "parent_amount_cents")
    val parentAmountCents: Long?,
    @param:Json(name = "items_total_amount_cents")
    val itemsTotalAmountCents: Long?,
    @param:Json(name = "mismatch_cents")
    val mismatchCents: Long?,
    @param:Json(name = "items_sum_status")
    val itemsSumStatus: String = "no_items",
    val items: List<ExpenseItemDto>,
)

data class ExpenseItemRequestDto(
    val name: String,
    val kind: String = "product",
    @param:Json(name = "quantity_text")
    val quantityText: String? = null,
    @param:Json(name = "unit_price_cents")
    val unitPriceCents: Long? = null,
    @param:Json(name = "amount_cents")
    val amountCents: Long? = null,
    val category: String? = null,
    @param:Json(name = "raw_text")
    val rawText: String? = null,
    val confidence: Double? = null,
)

data class ExpenseItemReplaceRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    val items: List<ExpenseItemRequestDto> = emptyList(),
)
