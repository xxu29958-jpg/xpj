package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.PendingGoalCreation
import com.ticketbox.data.repository.isSupportedGoalCreation
import com.ticketbox.data.repository.originalCreation
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

internal fun CreateDebtGoalViewModel.isCurrentDebtTask(original: DebtGoalCreationDraft): Boolean =
    binding == original.binding && edits.currentAccess()?.binding == original.binding &&
        task?.creationKey == original.creationKey && task?.viewingOriginalId == original.viewingOriginalId

internal fun CreateDebtGoalViewModel.presentDebtDraft(draft: DebtGoalCreationDraft) {
    _state.update { it.withDebtDraft(draft, edits.currentAccess()?.canModify == true) }
}

private fun CreateDebtGoalUiState.withDebtDraft(draft: DebtGoalCreationDraft, canModify: Boolean,
    original: PendingGoalCreation? = pending): CreateDebtGoalUiState {
    val request = original?.request?.takeIf { it.goalType == "debt_repayment" }
    val showAccepted = original?.let(draft::needsAcceptedDefinition) == true
    return copy(name = if (showAccepted) request?.name ?: draft.name else draft.name,
        selectedDebtIds = if (showAccepted) request?.debtPublicIds?.toSet() ?: draft.selectedIds.toSet() else draft.selectedIds.toSet(),
        formError = (if (draft.viewingOriginalId == null) draft.failure else draft.viewFailure)?.text(),
        canModify = canModify, pending = original,
        creationKey = if (draft.viewingOriginalId != null) original?.row?.idempotencyKey ?: draft.creationKey else draft.creationKey,
        hasDraft = draft.hasDraft, originalSubmissionId = original?.row?.id ?: draft.viewingOriginalId ?: draft.acceptedId,
        isViewingOriginal = draft.viewingOriginalId != null)
}

internal fun CreateDebtGoalViewModel.activateDebtGoalDraft() {
    lookupJob?.cancel(); observationJob?.cancel()
    val origin = binding
    if (origin == null) {
        task = null
        _state.value = CreateDebtGoalUiState(canModify = false)
        return
    }
    val current = store.read(origin) ?: DebtGoalCreationDraft(origin).also(store::write)
    val previous = task
    val continuation = _state.value.takeIf { previous != null && previous.binding == current.binding &&
        previous.creationKey == current.creationKey && previous.viewingOriginalId == current.viewingOriginalId }
    task = current
    _state.value = (continuation ?: CreateDebtGoalUiState())
        .withDebtDraft(current, edits.currentAccess()?.canModify == true)
        .copy(isSubmitting = current.viewingOriginalId == null &&
            submittingKey == current.creationKey && submitJob?.isActive == true)
    observeDebtGoalCreations()
    if (current.viewingOriginalId == null) lookupDebtGoalCreation()
}

internal fun CreateDebtGoalViewModel.updateDebtGoalDraft(change: (DebtGoalCreationDraft) -> DebtGoalCreationDraft) {
    val current = task ?: return
    val next = change(current)
    store.write(next)
    task = next
    presentDebtDraft(next)
}

internal fun CreateDebtGoalViewModel.applyDebtGoalOriginal(original: DebtGoalCreationDraft, pending: PendingGoalCreation) {
    val saved = if (original.viewingOriginalId == null) store.settle(original) {
        it.copy(acceptedId = pending.row.id)
    } else store.read(original.binding)
    if (!isCurrentDebtTask(original) || saved == null) return
    task = saved
    val request = pending.request?.takeIf { it.goalType == "debt_repayment" }
    val confirmed = pending.confirmed?.takeIf {
        pending.isDone && request?.isSupportedGoalCreation(pending.row) == true && it.isDebtRepayment
    }
    _state.update { it.withDebtDraft(saved, edits.currentAccess()?.canModify == true, pending).copy(
        checkingOriginal = false, acceptanceUncertain = false, createdPublicId = confirmed?.publicId,
        isSubmitting = original.viewingOriginalId == null && submittingKey == original.creationKey && submitJob?.isActive == true) }
}

private fun DebtGoalCreationDraft.needsAcceptedDefinition(pending: PendingGoalCreation): Boolean {
    if (viewingOriginalId != null) return true
    val request = pending.request?.takeIf { it.goalType == "debt_repayment" } ?: return false
    return request.isSupportedGoalCreation(pending.row) &&
        pending.row.status !in setOf(PendingMutationStatus.Unknown, PendingMutationStatus.Abandoned) &&
        (name.trim() != request.name || selectedIds.toSet() != request.debtPublicIds?.toSet())
}

internal fun CreateDebtGoalViewModel.observeDebtGoalCreations() {
    observationJob?.cancel()
    val original = task ?: return
    val revision = generation
    observationJob = viewModelScope.launch {
        edits.observeCreations(original.binding, original.creationKey.takeIf { original.viewingOriginalId == null },
            goalType = "debt_repayment", originalId = original.viewingOriginalId).catch { error ->
            if (isCurrentDebtTask(original) && generation == revision) settleDebtGoalFailure(original, error)
        }.collect { rows ->
            if (!isCurrentDebtTask(original) || generation != revision) return@collect
            val selected = if (original.viewingOriginalId != null) rows.firstOrNull { it.row.id == original.viewingOriginalId }
                else rows.firstOrNull { it.row.idempotencyKey == original.creationKey }
            if (selected != null) applyDebtGoalOriginal(original, selected)
            else if (original.viewingOriginalId != null) {
                updateDebtGoalDraft { it.copy(viewFailure = DebtGoalCreationFailure(resource = R.string.goal_creation_missing)) }
                _state.update { it.copy(pending = null, checkingOriginal = false, acceptanceUncertain = true, createdPublicId = null) }
            }
        }
    }
}

internal fun CreateDebtGoalViewModel.lookupDebtGoalCreation() {
    val original = task?.takeIf { it.viewingOriginalId == null } ?: return
    val revision = generation
    lookupJob?.cancel()
    _state.update { it.copy(checkingOriginal = true) }
    lookupJob = viewModelScope.launch {
        val result = edits.originalCreation(original.binding, original.creationKey)
        if (!isCurrentDebtTask(original) || generation != revision) return@launch
        val pending = result.getOrNull()
        when {
            result.isFailure -> settleDebtGoalFailure(original, requireNotNull(result.exceptionOrNull()))
            pending != null -> applyDebtGoalOriginal(original, pending)
            else -> {
                val uncertain = task?.publicationAttempted == true || task?.acceptedId != null
                if (uncertain && task?.failure == null) updateDebtGoalDraft {
                    it.copy(failure = DebtGoalCreationFailure(resource = R.string.goal_creation_missing))
                }
                _state.update { it.copy(checkingOriginal = false, acceptanceUncertain = uncertain,
                    pending = null, createdPublicId = null) }
            }
        }
    }
}

internal fun CreateDebtGoalViewModel.settleDebtGoalFailure(original: DebtGoalCreationDraft, error: Throwable,
    publicationRejected: Boolean = false) {
    val failure = error.debtGoalCreationFailure()
    val saved = store.settle(original) {
        if (original.viewingOriginalId == null) it.copy(failure = failure,
            publicationAttempted = if (publicationRejected) false else it.publicationAttempted) else it.copy(viewFailure = failure)
    } ?: return
    if (!isCurrentDebtTask(original)) return
    task = saved
    presentDebtDraft(saved)
    _state.update { it.copy(checkingOriginal = false, acceptanceUncertain = true) }
}
