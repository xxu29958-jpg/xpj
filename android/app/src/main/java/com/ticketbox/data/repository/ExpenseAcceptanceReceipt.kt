package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseConfirmationReceiptDto

internal const val EXPENSE_REJECTION_ORIGINAL_REQUIRES_REVIEW = "expense_rejection_original_requires_review"
internal const val EXPENSE_CONFIRMATION_ORIGINAL_REQUIRES_REVIEW = "expense_confirmation_original_requires_review"
internal const val EXPENSE_SUBTASK_ORIGINAL_REQUIRES_REVIEW = "expense_subtask_original_requires_review"
internal val EXPENSE_ORIGINAL_REVIEW_ERRORS = setOf(EXPENSE_REJECTION_ORIGINAL_REQUIRES_REVIEW,
    EXPENSE_CONFIRMATION_ORIGINAL_REQUIRES_REVIEW, EXPENSE_SUBTASK_ORIGINAL_REQUIRES_REVIEW)

/** Acceptance belongs to the same Outbox row; read-cache identity is disposable. */
@JsonClass(generateAdapter = true)
internal data class ExpenseAcceptanceReceipt(val expenseId: Long, val acceptedExpense: ExpenseDto? = null,
    val confirmationReceipt: ExpenseConfirmationReceiptDto? = null)

private val expenseAcceptanceReceiptAdapter by lazy {
    Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(ExpenseAcceptanceReceipt::class.java)
}

internal fun expenseAcceptanceReceiptJson(expenseId: Long): String =
    expenseAcceptanceReceiptAdapter.toJson(ExpenseAcceptanceReceipt(expenseId))

internal fun expenseAcceptanceReceiptJson(expense: ExpenseDto): String =
    expenseAcceptanceReceiptAdapter.toJson(ExpenseAcceptanceReceipt(expense.id, expense))

internal fun expenseAcceptanceReceiptJson(receipt: ExpenseConfirmationReceiptDto): String =
    expenseAcceptanceReceiptAdapter.toJson(ExpenseAcceptanceReceipt(receipt.id, confirmationReceipt = receipt))

internal fun expenseAcceptanceReceiptId(receiptJson: String?): Long? = receiptJson?.let { json ->
    runCatching { expenseAcceptanceReceiptAdapter.fromJson(json)?.expenseId?.takeIf { it > 0 } }.getOrNull()
}

/** Only the original accepted snapshot can supply a result or a rejection's Undo token. */
internal fun expenseAcceptanceReceiptSnapshot(row: OutboxRow): ExpenseDto? {
    val receipt = readExpenseAcceptanceReceipt(row) ?: return null
    val snapshot = receipt.acceptedExpense ?: return null
    return snapshot.takeIf { receipt.expenseId == it.id && validExpenseAcceptanceSnapshot(row, it) }
}

internal fun expenseConfirmationReceiptSnapshot(row: OutboxRow): ExpenseConfirmationReceiptDto? {
    val receipt = readExpenseAcceptanceReceipt(row) ?: return null
    return receipt.confirmationReceipt?.takeIf { it.id == receipt.expenseId && validExpenseConfirmationReceipt(row, it) }
}

private fun readExpenseAcceptanceReceipt(row: OutboxRow): ExpenseAcceptanceReceipt? =
    row.receiptJson?.takeIf { row.status == PendingMutationStatus.Done }?.let { json ->
        runCatching { expenseAcceptanceReceiptAdapter.fromJson(json) }.getOrNull()
    }

internal fun validExpenseConfirmationReceipt(row: OutboxRow, receipt: ExpenseConfirmationReceiptDto): Boolean {
    val ref = parseExpenseTargetRef(row.targetId) ?: return false
    return row.type == PendingMutationType.ConfirmExpense && receipt.id > 0 && receipt.rowVersion > 0 &&
        receipt.status == "confirmed" && (ref.toLongOrNull() == receipt.id ||
            (ref.startsWith("local:") && ref.removePrefix("local:").isNotBlank()))
}

internal fun validExpenseAcceptanceSnapshot(row: OutboxRow, expense: ExpenseDto): Boolean {
    val ref = parseExpenseTargetRef(row.targetId) ?: return false
    val expectedStatus = when (row.type) {
        PendingMutationType.RejectExpense -> expense.status == "rejected"
        PendingMutationType.UndoExpense -> expense.status == "pending" || expense.status == "confirmed"
        else -> false
    }
    val localAcceptance = row.type == PendingMutationType.RejectExpense && ref.startsWith("local:") &&
        ref.removePrefix("local:").isNotBlank()
    return expense.id > 0 && expense.rowVersion > 0 && expectedStatus &&
        (localAcceptance || ref.toLongOrNull() == expense.id)
}
