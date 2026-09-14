package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingExpenseCommand
import com.ticketbox.domain.model.Expense

/** Explicit observed command state; admission never manufactures a completion. */
internal fun observedExpenseCommand(
    id: Long,
    expense: Expense,
    type: PendingMutationType,
    status: PendingMutationStatus,
    binding: LogicalSessionBinding,
    acceptedExpense: Expense? = null,
): PendingExpenseCommand = PendingExpenseCommand(
    row = OutboxRow(
        id = id,
        serverUrl = binding.serverUrl,
        ledgerId = binding.ledgerId,
        ownerKey = binding.ownerKey,
        type = type,
        targetId = "expense:${expense.id}",
        payloadJson = "{}",
        expectedRowVersion = expense.rowVersion,
        status = status,
        retryCount = 0,
        lastError = null,
        createdAt = "2026-09-13T00:00:00Z",
        attemptedAt = null,
        completedAt = null,
        idempotencyKey = "original-$id",
    ),
    acceptedExpense = acceptedExpense,
)
