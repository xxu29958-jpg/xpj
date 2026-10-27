package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto

/** Applies already accepted server facts; DAO version fences remain the adoption authority. */
internal class ExpenseReceiptPublication(
    private val expenses: ExpenseDao,
    private val onConfirmedCommitted: (String) -> Unit,
) {
    suspend fun publishSnapshot(ledgerId: String, expense: ExpenseDto): Boolean {
        val accepted = expenses.applyServerExpense(ledgerId, expense.toEntity(ledgerId))
        if (accepted && expense.status == "confirmed") {
            notifyConfirmedExpenseWrite(ledgerId, onConfirmedCommitted)
        }
        return accepted
    }

    suspend fun publishBundle(ledgerId: String, bundle: ExpenseFactBundleDto) {
        val projection = bundle.toCacheProjection(ledgerId)
        val accepted = expenses.applyExpenseFactBundle(ledgerId, projection.root, projection.activeOffsets)
        if (accepted) notifyConfirmedExpenseWrite(ledgerId, onConfirmedCommitted)
    }

    suspend fun applyServerIdentity(ledgerId: String, clientRef: String, created: ExpenseDto) {
        expenses.applyLocalCreateServerIdentity(ledgerId, created.toEntity(ledgerId).copy(clientRef = clientRef))
    }
}
