package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Commands for replacing a debt goal's complete link set.
 *
 * The server remains authoritative: candidates are refreshed from the active ledger, replacement
 * carries the selected goal's current OCC row version, and a failed write deliberately leaves the
 * draft selection open so the user can recover without rebuilding it.
 */
internal class DebtGoalLinkEditorController(
    private val state: MutableStateFlow<DebtGoalUiState>,
    private val reports: ReportsActions,
    private val debts: DebtActions?,
    private val scope: CoroutineScope,
    private val onCommitted: (Goal) -> Unit,
) {
    private var editorGeneration = 0L
    private var activeSave: LinkEditorSaveAttempt? = null

    fun open() {
        val current = state.value
        val evaluation = current.selectedGoal?.debtRepayment ?: return
        if (!current.canModify || current.isSubmitting || debts == null) return
        invalidate()
        state.update {
            it.copy(
                linkEditorOpen = true,
                selectedDebtIds = evaluation.nonVoidedDebtPublicIds.toSet(),
                linkCandidates = emptyList(),
                isLinkEditorSnapshotFresh = false,
                linkEditorSnapshotRowVersion = null,
                error = null,
            )
        }
        reloadEditor(
            goalPublicId = current.selectedGoal.publicId,
            draftSelection = evaluation.nonVoidedDebtPublicIds.toSet(),
            useFreshSelection = true,
        )
    }

    fun close() {
        if (state.value.isSubmitting && activeSave != null) return
        invalidate()
        state.update {
            it.copy(
                linkEditorOpen = false,
                linkCandidates = emptyList(),
                selectedDebtIds = emptySet(),
                isLoadingLinkCandidates = false,
                isLinkEditorSnapshotFresh = false,
                linkEditorSnapshotRowVersion = null,
                error = null,
            )
        }
    }

    fun refresh() {
        val current = state.value
        val goalPublicId = current.selectedGoal?.publicId ?: return
        if (!current.linkEditorOpen || current.isSubmitting) return
        reloadEditor(
            goalPublicId = goalPublicId,
            draftSelection = current.selectedDebtIds,
            useFreshSelection = false,
        )
    }

    fun toggle(debtPublicId: String) {
        val current = state.value
        if (
            !current.linkEditorOpen ||
            !current.canModify ||
            current.isSubmitting ||
            current.isLoadingLinkCandidates
        ) {
            return
        }
        if (current.linkCandidates.none { it.publicId == debtPublicId }) return
        if (debtPublicId in current.selectedDebtIds && current.selectedDebtIds.size == 1) {
            state.update { it.copy(error = UiText.res(R.string.debt_goal_link_editor_needs_one)) }
            return
        }
        state.update {
            val selected = it.selectedDebtIds.toMutableSet()
            if (!selected.add(debtPublicId)) selected.remove(debtPublicId)
            it.copy(selectedDebtIds = selected, error = null)
        }
    }

    fun save() {
        val current = state.value
        val goal = current.selectedGoal ?: return
        if (
            current.linkEditorOpen &&
            current.isLinkEditorSnapshotFresh &&
            current.linkEditorSnapshotRowVersion != goal.rowVersion
        ) {
            reloadEditor(
                goalPublicId = goal.publicId,
                draftSelection = current.selectedDebtIds,
                useFreshSelection = false,
                completionError = UiText.res(R.string.debt_goal_link_editor_conflict_refreshed),
            )
            return
        }
        if (
            !current.linkEditorOpen ||
            !current.canModify ||
            current.isSubmitting ||
            current.isLoadingLinkCandidates ||
            !current.isLinkEditorSnapshotFresh
        ) {
            return
        }
        val orderedSelection = current.linkCandidates
            .map(Debt::publicId)
            .filter(current.selectedDebtIds::contains)
        if (orderedSelection.isEmpty()) {
            state.update { it.copy(error = UiText.res(R.string.debt_goal_link_editor_needs_one)) }
            return
        }
        val attempt = LinkEditorSaveAttempt(
            identity = LinkEditorIdentity(editorGeneration, goal.publicId),
            expectedRowVersion = goal.rowVersion,
            draftSelection = current.selectedDebtIds,
        )
        submitSave(attempt, orderedSelection)
    }

    private fun submitSave(
        attempt: LinkEditorSaveAttempt,
        orderedSelection: List<String>,
    ) {
        activeSave = attempt
        state.update { it.copy(isSubmitting = true, error = null) }
        scope.launch {
            val result = reports.replaceDebtLinks(
                attempt.identity.goalPublicId,
                attempt.expectedRowVersion,
                orderedSelection,
            )
            if (!attempt.isCurrent(editorGeneration, activeSave, state.value)) return@launch
            result.fold(
                onSuccess = { updated -> handleSaveSuccess(attempt, updated) },
                onFailure = { error ->
                    handleSaveFailure(
                        attempt,
                        normalizedSaveError(
                            attempt = attempt,
                            selectedGoalRowVersion = state.value.selectedGoal?.rowVersion,
                            error = error,
                        ),
                    )
                },
            )
        }
    }

    private fun handleSaveSuccess(attempt: LinkEditorSaveAttempt, updated: Goal) {
        if (updated.publicId != attempt.identity.goalPublicId) {
            activeSave = null
            state.update {
                it.copy(
                    isSubmitting = false,
                    isLinkEditorSnapshotFresh = false,
                    linkEditorSnapshotRowVersion = null,
                    error = UiText.res(R.string.debt_goal_link_editor_load_failed),
                )
            }
            return
        }
        activeSave = null
        editorGeneration += 1
        onCommitted(updated)
    }

    /** Invalidates every in-flight read/write when the editor's owning page is closed or replaced. */
    fun invalidate() {
        editorGeneration += 1
        val ownedSubmission = activeSave != null
        activeSave = null
        state.update {
            it.copy(
                isSubmitting = if (ownedSubmission) false else it.isSubmitting,
                isLinkEditorSnapshotFresh = false,
                linkEditorSnapshotRowVersion = null,
            )
        }
    }

    private fun reloadEditor(
        goalPublicId: String,
        draftSelection: Set<String>,
        useFreshSelection: Boolean,
        completionError: UiText? = null,
    ) {
        val debtActions = debts ?: return
        val current = state.value
        if (
            !current.linkEditorOpen ||
            current.isSubmitting ||
            current.selectedGoal?.publicId != goalPublicId
        ) {
            return
        }
        activeSave = null
        val identity = LinkEditorIdentity(++editorGeneration, goalPublicId)
        state.update {
            it.copy(
                isSubmitting = false,
                isLoadingLinkCandidates = true,
                isLinkEditorSnapshotFresh = false,
                linkEditorSnapshotRowVersion = null,
                error = null,
            )
        }
        scope.launch {
            loadEditorSnapshot(
                identity = identity,
                debtActions = debtActions,
                draftSelection = draftSelection,
                useFreshSelection = useFreshSelection,
                completionError = completionError,
            )
        }
    }

    private suspend fun loadEditorSnapshot(
        identity: LinkEditorIdentity,
        debtActions: DebtActions,
        draftSelection: Set<String>,
        useFreshSelection: Boolean,
        completionError: UiText?,
    ) {
        val freshGoal = reports.goal(identity.goalPublicId).getOrElse { error ->
            state.finishReloadFailure(identity, editorGeneration, error)
            return
        }
        val rows = debtActions.listDebts().getOrElse { error ->
            state.finishReloadFailure(identity, editorGeneration, error)
            return
        }
        if (
            !identity.isCurrent(editorGeneration, state.value) ||
            freshGoal.publicId != identity.goalPublicId
        ) {
            return
        }
        state.publishEditorSnapshot(
            identity = identity,
            currentGeneration = editorGeneration,
            freshGoal = freshGoal,
            snapshot = linkEditorSnapshot(freshGoal, rows, draftSelection, useFreshSelection),
            completionError = completionError,
        )
    }

    private fun handleSaveFailure(attempt: LinkEditorSaveAttempt, error: Throwable) {
        if (!attempt.isCurrent(editorGeneration, activeSave, state.value)) return
        activeSave = null
        val isConflict = (error as? RepositoryException)?.errorCode == STATE_CONFLICT
        state.update { latest ->
            if (!attempt.identity.isCurrent(editorGeneration, latest)) {
                latest
            } else {
                latest.copy(
                    isSubmitting = false,
                    isLinkEditorSnapshotFresh = !isConflict,
                    linkEditorSnapshotRowVersion =
                        if (isConflict) null else latest.linkEditorSnapshotRowVersion,
                    error = if (isConflict) null else error.toUiText(R.string.debt_goal_update_failed),
                )
            }
        }
        if (isConflict) {
            reloadEditor(
                goalPublicId = attempt.identity.goalPublicId,
                draftSelection = attempt.draftSelection,
                useFreshSelection = false,
                completionError = UiText.res(R.string.debt_goal_link_editor_conflict_refreshed),
            )
        }
    }
}

private data class LinkEditorIdentity(
    val generation: Long,
    val goalPublicId: String,
)

private data class LinkEditorSaveAttempt(
    val identity: LinkEditorIdentity,
    val expectedRowVersion: Long,
    val draftSelection: Set<String>,
)

private data class LinkEditorSnapshot(
    val candidates: List<Debt>,
    val selection: Set<String>,
)

private fun LinkEditorIdentity.isCurrent(
    currentGeneration: Long,
    currentState: DebtGoalUiState,
): Boolean = generation == currentGeneration &&
    currentState.linkEditorOpen &&
    currentState.selectedGoal?.publicId == goalPublicId

private fun LinkEditorSaveAttempt.isCurrent(
    currentGeneration: Long,
    currentAttempt: LinkEditorSaveAttempt?,
    currentState: DebtGoalUiState,
): Boolean = this == currentAttempt && identity.isCurrent(currentGeneration, currentState)

private fun normalizedSaveError(
    attempt: LinkEditorSaveAttempt,
    selectedGoalRowVersion: Long?,
    error: Throwable,
): Throwable = if (selectedGoalRowVersion != attempt.expectedRowVersion) {
    RepositoryException(
        message = "The goal snapshot changed while links were being saved.",
        errorCode = STATE_CONFLICT,
    )
} else {
    error
}

private fun MutableStateFlow<DebtGoalUiState>.finishReloadFailure(
    identity: LinkEditorIdentity,
    currentGeneration: Long,
    error: Throwable,
) {
    if (!identity.isCurrent(currentGeneration, value)) return
    update { latest ->
        if (!identity.isCurrent(currentGeneration, latest)) {
            latest
        } else {
            latest.copy(
                isLoadingLinkCandidates = false,
                error = error.toUiText(R.string.debt_goal_link_editor_load_failed),
            )
        }
    }
}

private fun MutableStateFlow<DebtGoalUiState>.publishEditorSnapshot(
    identity: LinkEditorIdentity,
    currentGeneration: Long,
    freshGoal: Goal,
    snapshot: LinkEditorSnapshot,
    completionError: UiText?,
) {
    update { latest ->
        if (!identity.isCurrent(currentGeneration, latest)) {
            latest
        } else {
            latest.copy(
                selectedGoal = freshGoal,
                goals = latest.goals.map { goal ->
                    if (goal.publicId == freshGoal.publicId) freshGoal else goal
                },
                linkCandidates = snapshot.candidates,
                selectedDebtIds = snapshot.selection,
                isLoadingLinkCandidates = false,
                isLinkEditorSnapshotFresh = true,
                linkEditorSnapshotRowVersion = freshGoal.rowVersion,
                error = completionError,
            )
        }
    }
}

private fun linkEditorSnapshot(
    freshGoal: Goal,
    rows: List<Debt>,
    draftSelection: Set<String>,
    useFreshSelection: Boolean,
): LinkEditorSnapshot {
    val serverSelection = freshGoal.debtRepayment?.nonVoidedDebtPublicIds.orEmpty().toSet()
    val retainedIds = draftSelection + serverSelection
    val candidates = rows.filter { debt ->
        debt.isOpen || (debt.publicId in retainedIds && !debt.isVoided)
    }
    val candidateIds = candidates.mapTo(mutableSetOf(), Debt::publicId)
    val preferredSelection = if (useFreshSelection) serverSelection else draftSelection
    val rebasedSelection = preferredSelection.intersect(candidateIds)
        .ifEmpty { serverSelection.intersect(candidateIds) }
    return LinkEditorSnapshot(candidates = candidates, selection = rebasedSelection)
}

private const val STATE_CONFLICT = "state_conflict"
