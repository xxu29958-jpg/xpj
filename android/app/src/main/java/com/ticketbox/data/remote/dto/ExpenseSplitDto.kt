package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class ExpenseSplitDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val position: Int,
    @param:Json(name = "member_id")
    val memberId: Long,
    @param:Json(name = "account_name")
    val accountName: String,
    val role: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val note: String?,
    @param:Json(name = "disabled_at")
    val disabledAt: String?,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
)

data class ExpenseSplitsResponseDto(
    @param:Json(name = "expense_id")
    val expenseId: Long,
    // ADR-0041: parent expense's post-mutation row_version (see
    // ExpenseItemsResponseDto). Self-describing replace response — no second GET.
    @param:Json(name = "row_version")
    val rowVersion: Long,
    @param:Json(name = "parent_amount_cents")
    val parentAmountCents: Long?,
    @param:Json(name = "splits_total_amount_cents")
    val splitsTotalAmountCents: Long?,
    @param:Json(name = "mismatch_cents")
    val mismatchCents: Long?,
    val splits: List<ExpenseSplitDto>,
)

data class ExpenseSplitRequestDto(
    @param:Json(name = "member_id")
    val memberId: Long,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val note: String? = null,
)

data class ExpenseSplitReplaceRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    val splits: List<ExpenseSplitRequestDto> = emptyList(),
)
