package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseDto

internal const val EXPENSE_REJECTION_ORIGINAL_REQUIRES_REVIEW = "expense_rejection_original_requires_review"

/** Acceptance belongs to the same Outbox row; read-cache identity is disposable. */
@JsonClass(generateAdapter = true)
internal data class ExpenseAcceptanceReceipt(val expenseId: Long, val acceptedExpense: ExpenseDto? = null)

private val expenseAcceptanceReceiptAdapter by lazy {
    Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(ExpenseAcceptanceReceipt::class.java)
}

internal fun expenseAcceptanceReceiptJson(expenseId: Long): String =
    expenseAcceptanceReceiptAdapter.toJson(ExpenseAcceptanceReceipt(expenseId))

internal fun expenseAcceptanceReceiptJson(expense: ExpenseDto): String =
    expenseAcceptanceReceiptAdapter.toJson(ExpenseAcceptanceReceipt(expense.id, expense))

internal fun expenseAcceptanceReceiptId(receiptJson: String?): Long? = receiptJson?.let { json ->
    runCatching { expenseAcceptanceReceiptAdapter.fromJson(json)?.expenseId?.takeIf { it > 0 } }.getOrNull()
}

/** Only the original accepted snapshot can supply a rejection's Undo token. */
internal fun expenseAcceptanceReceiptSnapshot(row: OutboxRow): ExpenseDto? {
    if (row.status != PendingMutationStatus.Done) return null
    val receipt = row.receiptJson?.let { json ->
        runCatching { expenseAcceptanceReceiptAdapter.fromJson(json) }.getOrNull()
    } ?: return null
    val snapshot = receipt.acceptedExpense ?: return null
    return snapshot.takeIf { receipt.expenseId == it.id && validExpenseAcceptanceSnapshot(row, it) }
}

internal fun validExpenseAcceptanceSnapshot(row: OutboxRow, expense: ExpenseDto): Boolean {
    val ref = parseExpenseTargetRef(row.targetId) ?: return false
    val expectedStatus = when (row.type) {
        PendingMutationType.RejectExpense -> expense.status == "rejected"
        PendingMutationType.UndoExpense -> expense.status == "pending" || expense.status == "confirmed"
        else -> false
    }
    val localReject = row.type == PendingMutationType.RejectExpense && ref.startsWith("local:") &&
        ref.removePrefix("local:").isNotBlank()
    return expense.id > 0 && expense.rowVersion > 0 && expectedStatus &&
        (localReject || ref.toLongOrNull() == expense.id)
}
