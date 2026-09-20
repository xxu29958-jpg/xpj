package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

fun ExpenseEditViewModel.originalCommandAccepted() {
    _uiState.update { it.copy(originalBaselineRequired = true, thumbnail = null, fullImage = null) }
}

/** Explicitly adopt only attachment changes; concurrent financial changes keep the user's original OCC. */
fun ExpenseEditViewModel.reviewOriginalBaseline() {
    val before = uiState.value
    val expense = before.expense ?: return
    val binding = fxBinding ?: return
    if (before.expenseLoading || before.saving || before.itemsSaving || before.splitsSaving || before.commandRowIds.isNotEmpty()) return
    _uiState.update { it.copy(expenseLoading = true) }
    viewModelScope.launch {
        val result = repository.fetchExpenseForFxReview(binding, expense.id).mapCatching { fresh ->
            OriginalEditorBaseline(fresh, repository.fetchExpenseItems(expense.id).getOrThrow(),
                repository.fetchExpenseSplits(expense.id).getOrThrow())
        }
        if (binding != repository.captureDeferredLedgerBinding()) return@launch
        result.onSuccess { fresh ->
            _uiState.update {
                if (it.expense != expense || !fresh.matches(before)) it.copy(expenseLoading = false,
                    message = UiText.res(R.string.original_edit_changed))
                else it.copy(expense = fresh.expense, expenseItems = fresh.items, expenseSplits = fresh.splits,
                    expenseLoading = false, originalBaselineRequired = false,
                    preservedFormTimestamp = it.preservedFormTimestamp ?: expense.updatedAt)
            }
        }.onFailure { error ->
            _uiState.update { it.copy(expenseLoading = false, message = error.toUiText(R.string.original_health_failed)) }
        }
    }
}

private data class OriginalEditorBaseline(val expense: Expense, val items: ExpenseItems, val splits: ExpenseSplits) {
    fun matches(before: ExpenseEditUiState): Boolean {
        val previous = before.expense ?: return false
        val oldItems = before.expenseItems ?: return false
        val oldSplits = before.expenseSplits ?: return false
        return expense.differsOnlyInOriginal(previous) && items.parentRowVersion == expense.rowVersion &&
            splits.parentRowVersion == expense.rowVersion &&
            items.copy(parentRowVersion = oldItems.parentRowVersion) == oldItems &&
            splits.copy(parentRowVersion = oldSplits.parentRowVersion) == oldSplits
    }
}

private fun Expense.differsOnlyInOriginal(previous: Expense): Boolean = rowVersion >= previous.rowVersion && copy(
    rowVersion = previous.rowVersion, updatedAt = previous.updatedAt, imagePath = previous.imagePath,
    hasImage = previous.hasImage, thumbnailPath = previous.thumbnailPath, imageHash = previous.imageHash,
    imageDeletedAt = previous.imageDeletedAt, thumbnailDeletedAt = previous.thumbnailDeletedAt,
) == previous

fun ExpenseFactViewModel.refreshOriginalFact() {
    thumbnailLoadGeneration++
    fullImageLoadGeneration++
    _uiState.update { it.copy(thumbnail = null, fullImage = null, imageLoading = false) }
    refreshCorrectionFact()
}
