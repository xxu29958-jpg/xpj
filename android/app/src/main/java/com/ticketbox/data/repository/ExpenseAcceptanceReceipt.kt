package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi

/** Acceptance belongs to the same Outbox row; read-cache identity is disposable. */
@JsonClass(generateAdapter = true)
internal data class ExpenseAcceptanceReceipt(val expenseId: Long)

private val expenseAcceptanceReceiptAdapter by lazy {
    Moshi.Builder().build().adapter(ExpenseAcceptanceReceipt::class.java)
}

internal fun expenseAcceptanceReceiptJson(expenseId: Long): String =
    expenseAcceptanceReceiptAdapter.toJson(ExpenseAcceptanceReceipt(expenseId))

internal fun expenseAcceptanceReceiptId(receiptJson: String?): Long? = receiptJson?.let { json ->
    runCatching { expenseAcceptanceReceiptAdapter.fromJson(json)?.expenseId?.takeIf { it > 0 } }.getOrNull()
}
