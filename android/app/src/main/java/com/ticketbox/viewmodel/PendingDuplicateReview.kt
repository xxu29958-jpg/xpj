package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

fun PendingViewModel.setDuplicateDecision(confirmed: Boolean) {
    _uiState.update { state ->
        val sheet = state.activeSheet as? PendingSheet.Duplicate
        if (sheet == null || state.readOnly || sheet.referenceLoading || sheet.expense.id in state.actionInProgressIds) state
        else state.copy(activeSheet = sheet.copy(keepBothConfirmed = confirmed))
    }
}

/** Comparison is a bound query. The open expense remains the original command basis. */
fun PendingViewModel.loadDuplicateReference() {
    val sheet = _uiState.value.activeSheet as? PendingSheet.Duplicate ?: return
    if (sheet.referenceLoading) return
    val binding = commandBinding() ?: return
    val referenceId = sheet.expense.duplicateOfId
    if (referenceId == null) {
        _uiState.update { it.copy(activeSheet = sheet.copy(referenceMessage = UiText.res(R.string.pending_duplicate_reference_absent))) }
        return
    }
    val loading = sheet.copy(referenceLoading = true, referenceMessage = null)
    _uiState.update { it.copy(activeSheet = loading) }
    viewModelScope.launch {
        val loaded = readDuplicateReference(loading, referenceId, binding)
        if (!holdsCommandBinding(binding) || _uiState.value.activeSheet !== loading) return@launch
        _uiState.update { it.copy(activeSheet = loaded) }
        val reference = loaded.reference
        if (reference?.hasUndeletedImage == true) {
            val image = repository.fetchThumbnail(reference.id).getOrNull()
            if (holdsCommandBinding(binding)) _uiState.update {
                val current = it.activeSheet as? PendingSheet.Duplicate
                if (current != null && current.expense === loaded.expense && current.reference === reference && !current.referenceLoading) {
                    it.copy(activeSheet = current.copy(referenceThumbnail = image))
                } else it
            }
        }
    }
}

private suspend fun PendingViewModel.readDuplicateReference(
    loading: PendingSheet.Duplicate, referenceId: Long, binding: LogicalSessionBinding,
): PendingSheet.Duplicate {
    val remote = expenseReader.fetchExpense(referenceId, binding)
    val denied = (remote.exceptionOrNull() as? RepositoryException)?.httpStatusCode in setOf(401, 403, 404)
    val cached = if (remote.isFailure && !denied && holdsCommandBinding(binding)) {
        expenseReader.fetchExpenseFromLocalCache(referenceId, binding).getOrNull()
    } else null
    return loading.copy(reference = remote.getOrNull() ?: cached, referenceLoading = false,
        referenceMessage = when {
            cached != null -> UiText.res(R.string.pending_duplicate_reference_cached)
            remote.isFailure -> remote.exceptionOrNull()?.toUiText(R.string.pending_duplicate_reference_failed)
            else -> null
        })
}
