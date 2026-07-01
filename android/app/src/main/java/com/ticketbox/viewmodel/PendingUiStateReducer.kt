package com.ticketbox.viewmodel

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.UiText

internal object PendingUiStateReducer {
    fun afterRefresh(
        current: PendingUiState,
        expenses: List<Expense>,
        readOnly: Boolean,
    ): PendingUiState {
        val activeIds = expenses.map { expense -> expense.id }.toSet()
        return current.copy(
            items = expenses,
            thumbnails = current.thumbnails.filterKeys { id -> id in activeIds },
            activeSheet = reconcileActiveSheet(current.activeSheet, expenses),
            readOnly = readOnly,
            showingCachedSnapshot = false,
            hasLoadedOnce = true,
            loading = false,
        )
    }

    fun afterLoadedThumbnails(
        current: PendingUiState,
        loaded: Map<Long, ProtectedImage>,
    ): PendingUiState {
        val activeIds = current.items.map { expense -> expense.id }.toSet()
        return current.copy(thumbnails = current.thumbnails + loaded.filterKeys { id -> id in activeIds })
    }

    fun afterConfirmed(
        current: PendingUiState,
        confirmed: Expense,
        message: UiText?,
    ): PendingUiState = afterRemoved(
        current = current,
        expenseId = confirmed.id,
        closeSheet = false,
        message = message,
    )

    fun afterRejected(
        current: PendingUiState,
        rejected: Expense,
        message: UiText?,
    ): PendingUiState = afterRemoved(
        current = current,
        expenseId = rejected.id,
        closeSheet = true,
        message = message,
    )

    fun afterUpdated(
        current: PendingUiState,
        updated: Expense,
        closeSheet: Boolean,
        message: UiText?,
        clearInProgress: Boolean = true,
    ): PendingUiState {
        val updatedItems = current.items.map { expense -> if (expense.id == updated.id) updated else expense }
        return current.copy(
            items = updatedItems,
            actionInProgressIds = if (clearInProgress) {
                current.actionInProgressIds - updated.id
            } else {
                current.actionInProgressIds
            },
            activeSheet = if (closeSheet) PendingSheet.None else reconcileActiveSheet(current.activeSheet, updatedItems),
            message = message ?: current.message,
        )
    }

    private fun afterRemoved(
        current: PendingUiState,
        expenseId: Long,
        closeSheet: Boolean,
        message: UiText?,
    ): PendingUiState {
        val remainingItems = current.items.filterNot { expense -> expense.id == expenseId }
        return current.copy(
            items = remainingItems,
            thumbnails = current.thumbnails - expenseId,
            actionInProgressIds = current.actionInProgressIds - expenseId,
            activeSheet = if (closeSheet) PendingSheet.None else reconcileActiveSheet(current.activeSheet, remainingItems),
            message = message ?: current.message,
        )
    }
}
