package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.PendingGoalCreation
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.newTaskMonth
import com.ticketbox.data.repository.originalCreation
import com.ticketbox.data.repository.isSupportedGoalCreation
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.formatAmountInput
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch

internal fun CreateSpendingGoalViewModel.isCurrentGoalTask(original: SpendingGoalCreationDraft): Boolean =
    binding == original.binding && edits.currentAccess()?.binding == original.binding && task?.creationKey == original.creationKey

internal fun CreateSpendingGoalViewModel.activateGoalDraft() {
    val origin = binding
    if (origin == null) {
        task = null
        mutableState.value = CreateSpendingGoalUiState(canModify = false)
        return
    }
    val current = store.read(origin) ?: SpendingGoalCreationDraft(origin, monthReady = calendars == null).also(store::write)
    task = current
    mutableState.value = current.presentation(edits.currentAccess()?.canModify == true)
        .copy(isSubmitting = current.viewingOriginalId == null && submittingKey == current.creationKey && submitJob?.isActive == true)
    observeGoalCreations()
    if (current.viewingOriginalId != null) return
    lookupGoalCreation()
    if (current.currencyCode == null && current.acceptedId == null) retryCurrency()
    resolveGoalTaskMonth()
}

internal fun CreateSpendingGoalViewModel.updateGoalDraft(change: (SpendingGoalCreationDraft) -> SpendingGoalCreationDraft) {
    val current = task ?: return
    val next = change(current)
    store.write(next)
    task = next
    val previous = state.value
    mutableState.value = next.presentation(previous.canModify).copy(isSubmitting = previous.isSubmitting,
        pending = previous.pending, createdPublicId = previous.createdPublicId,
        acceptanceUncertain = previous.acceptanceUncertain, checkingOriginal = previous.checkingOriginal)
}

internal fun CreateSpendingGoalViewModel.resolveGoalTaskMonth() {
    val original = task?.takeUnless { it.monthSelected || it.monthReady || it.acceptedId != null } ?: return
    val revision = generation
    viewModelScope.launch {
        val month = calendars.newTaskMonth(original.binding)
        if (!isCurrentGoalTask(original) || generation != revision || task?.viewingOriginalId != null || task?.acceptedId != null) return@launch
        updateGoalDraft { it.copy(month = if (it.monthSelected) it.month else month, monthReady = true) }
    }
}

internal fun CreateSpendingGoalViewModel.observeGoalCreations() {
    observationJob?.cancel()
    val original = task ?: return
    val revision = generation
    observationJob = viewModelScope.launch {
        edits.observeCreations(original.binding, original.creationKey.takeIf { original.viewingOriginalId == null }).catch { error ->
            if (isCurrentGoalTask(original) && generation == revision) settleGoalFailure(original, error, SpendingGoalFailureKind.Lookup)
        }.collect { rows ->
            if (!isCurrentGoalTask(original) || generation != revision) return@collect
            val selected = if (original.viewingOriginalId != null) rows.firstOrNull { it.row.id == original.viewingOriginalId }
                else rows.firstOrNull { it.row.idempotencyKey == original.creationKey }
            if (selected != null) applyGoalOriginal(original, selected)
            else if (original.viewingOriginalId != null) mutableState.update { it.copy(pending = null, isSubmitting = false,
                formError = UiText.res(R.string.goal_creation_missing)) }
        }
    }
}

internal fun CreateSpendingGoalViewModel.applyGoalOriginal(original: SpendingGoalCreationDraft, pending: PendingGoalCreation) {
    val saved = if (original.viewingOriginalId == null) store.settle(original) {
        it.copy(acceptedId = pending.row.id, failure = it.failure?.takeIf { failure -> failure.kind == SpendingGoalFailureKind.Recovery })
    }
        else store.read(original.binding)
    if (!isCurrentGoalTask(original) || saved == null || saved.viewingOriginalId != original.viewingOriginalId) return
    task = saved
    mutableState.value = saved.presentation(edits.currentAccess()?.canModify == true).withGoalOriginal(pending)
        .copy(isSubmitting = submittingKey == original.creationKey && submitJob?.isActive == true)
}

internal fun CreateSpendingGoalViewModel.lookupGoalCreation() {
    val original = task?.takeIf { it.viewingOriginalId == null } ?: return
    val revision = generation
    lookupJob?.cancel()
    mutableState.update { it.copy(checkingOriginal = true) }
    lookupJob = viewModelScope.launch {
        val result = edits.originalCreation(original.binding, original.creationKey)
        if (!isCurrentGoalTask(original) || generation != revision || task?.viewingOriginalId != null) return@launch
        val pending = result.getOrNull()
        when {
            result.isFailure -> {
                updateGoalDraft { it.copy(failure = requireNotNull(result.exceptionOrNull()).goalCreationFailure(SpendingGoalFailureKind.Lookup)) }
                mutableState.update { it.copy(checkingOriginal = false, acceptanceUncertain = true) }
            }
            pending != null -> applyGoalOriginal(original, pending)
            else -> {
                val uncertain = task?.publicationAttempted == true || task?.acceptedId != null
                updateGoalDraft { it.copy(failure = if (uncertain) it.failure ?: SpendingGoalCreationFailure(SpendingGoalFailureKind.MissingOriginal)
                    else it.failure?.takeUnless { failure -> failure.kind in setOf(SpendingGoalFailureKind.Lookup, SpendingGoalFailureKind.MissingOriginal) }) }
                mutableState.update { it.copy(checkingOriginal = false, acceptanceUncertain = uncertain,
                    pending = null, createdPublicId = null) }
            }
        }
    }
}

internal suspend fun CreateSpendingGoalViewModel.submitGoalTask(original: SpendingGoalCreationDraft, draft: GoalDraft) {
    try {
        val lookup = edits.originalCreation(original.binding, original.creationKey)
        val known = lookup.getOrNull()
        if (lookup.isFailure) {
            settleGoalFailure(original, requireNotNull(lookup.exceptionOrNull()), SpendingGoalFailureKind.Lookup)
        } else if (known != null) {
            applyGoalOriginal(original, known)
        } else {
            val publication = store.settle(original) { it.copy(publicationAttempted = true) } ?: return
            if (isCurrentGoalTask(original)) task = publication
            val result = edits.create(original.binding, draft, original.creationKey)
            if (result.isSuccess) {
                val settled = store.settle(original) { it.copy(acceptedId = result.getOrThrow(), failure = null) }
                if (isCurrentGoalTask(original) && settled != null && settled.viewingOriginalId == null) {
                    task = settled
                }
            } else settleGoalFailure(original, requireNotNull(result.exceptionOrNull()), SpendingGoalFailureKind.Create)
        }
    } finally {
        if (submittingKey == original.creationKey) {
            submittingKey = null
            if (isCurrentGoalTask(original)) mutableState.update { it.copy(isSubmitting = false,
                acceptanceUncertain = it.pending == null && task?.publicationAttempted == true) }
        }
    }
    if (isCurrentGoalTask(original) && task?.viewingOriginalId == null) lookupGoalCreation()
}

internal fun CreateSpendingGoalViewModel.settleGoalFailure(original: SpendingGoalCreationDraft, error: Throwable, kind: SpendingGoalFailureKind) {
    val failure = error.goalCreationFailure(kind)
    val settled = store.settle(original) {
        if (original.viewingOriginalId != null) it.copy(viewFailure = failure)
        else it.copy(failure = failure, publicationAttempted = if (kind == SpendingGoalFailureKind.Create) false else it.publicationAttempted)
    } ?: return
    if (!isCurrentGoalTask(original) || settled.viewingOriginalId != original.viewingOriginalId) return
    task = settled
    mutableState.value = if (settled.viewingOriginalId != null) state.value.copy(formError = failure.text())
        else settled.presentation(edits.currentAccess()?.canModify == true).copy(acceptanceUncertain = true)
}

private fun CreateSpendingGoalUiState.withGoalOriginal(original: PendingGoalCreation): CreateSpendingGoalUiState {
    val request = original.request?.takeIf { it.isSupportedGoalCreation(original.row) &&
        original.row.status !in setOf(PendingMutationStatus.Unknown, PendingMutationStatus.Abandoned) }
    val currency = CurrencyCode.fromStorageKeyOrNull(request?.homeCurrencyCode)
    return copy(pending = original, originalSubmissionId = original.row.id, monthReady = true,
        name = request?.name ?: name, month = request?.month ?: month, category = if (request == null) category else request.category.orEmpty(),
        ledgerCurrency = if (request == null) ledgerCurrency else currency,
        targetAmountInput = if (request == null) targetAmountInput else if (currency != null) formatAmountInput(request.targetAmountCents, currency)
            else request.targetAmountCents?.toString().orEmpty(),
        createdPublicId = original.confirmed?.publicId?.takeIf { original.isDone })
}
