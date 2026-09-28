package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.PendingGoalCreation
import com.ticketbox.data.repository.createDebtGoal
import com.ticketbox.data.repository.originalCreation
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

internal suspend fun CreateDebtGoalViewModel.submitDebtGoalTask(original: DebtGoalCreationDraft, name: String, ids: List<String>) {
    val revision = generation
    try {
        val lookup = edits.originalCreation(original.binding, original.creationKey)
        if (!isCurrentDebtTask(original) || generation != revision) return
        val known = lookup.getOrNull()
        when {
            lookup.isFailure -> settleDebtGoalFailure(original, requireNotNull(lookup.exceptionOrNull()))
            known != null -> applyDebtGoalOriginal(original, known)
            task?.publicationAttempted == true -> _state.update { it.copy(acceptanceUncertain = true) }
            !canPublishDebtSelection(ids) -> updateDebtGoalDraft {
                it.copy(failure = DebtGoalCreationFailure(resource = R.string.debt_goal_create_selection_changed))
            }
            else -> {
                val publication = store.settle(original) { it.copy(publicationAttempted = true) } ?: return
                task = publication
                val result = edits.createDebtGoal(original.binding, name, ids, original.creationKey)
                if (result.isSuccess) {
                    val saved = store.settle(original) { it.copy(acceptedId = result.getOrThrow(), failure = null) }
                    if (isCurrentDebtTask(original) && saved != null) task = saved
                } else settleDebtGoalFailure(original, requireNotNull(result.exceptionOrNull()), publicationRejected = true)
            }
        }
    } finally {
        finishDebtGoalPublication(original)
    }
    if (isCurrentDebtTask(original)) lookupDebtGoalCreation()
}

internal fun CreateDebtGoalViewModel.recoverDebtGoalOriginal(pending: PendingGoalCreation, drop: Boolean) {
    val original = task ?: return
    val revision = generation
    _state.update { it.copy(isSubmitting = true, formError = null) }
    submitJob = viewModelScope.launch {
        try {
            val result = edits.recoverCreation(original.binding, pending, drop)
            if (!isCurrentDebtTask(original) || generation != revision) return@launch
            if (result.isFailure) settleDebtGoalFailure(original, requireNotNull(result.exceptionOrNull()))
            else retryOriginalAfterRecovery()
        } finally {
            if (isCurrentDebtTask(original)) _state.update { it.copy(isSubmitting = false) }
        }
    }
}

private fun CreateDebtGoalViewModel.retryOriginalAfterRecovery() {
    observeDebtGoalCreations()
    if (task?.viewingOriginalId == null) lookupDebtGoalCreation()
}

private fun CreateDebtGoalViewModel.finishDebtGoalPublication(original: DebtGoalCreationDraft) {
    if (submittingKey != original.creationKey) return
    submittingKey = null
    if (isCurrentDebtTask(original)) _state.update { it.copy(isSubmitting = false,
        acceptanceUncertain = it.pending == null && task?.publicationAttempted == true) }
}

internal fun CreateDebtGoalViewModel.canPublishDebtSelection(ids: List<String>): Boolean =
        edits.currentAccess()?.canModify == true && writes.currentAccess()?.binding == binding &&
            writeObservation?.binding == binding && state.value.loadError == null &&
            state.value.unavailableSelectedDebtIds.isEmpty() && ids.none { "debt:$it" in writeObservation?.unresolvedTargetIds.orEmpty() }
