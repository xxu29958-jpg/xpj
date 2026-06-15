package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0049 §6 (slice 7) debt_repayment goal screen state + actions.
 *
 * Reuses the goal repository ([ReportsActions]) — a debt_repayment goal is a goal
 * (same table / DTO). The screen is a list → detail flow inside one overlay; the
 * detail surfaces the §6/F13 integrity review with its two exits:
 *  - remove the debt-voided link(s) via [removeVoidedDebts] (link-replace → new version)
 *  - keep it for audit via [acknowledge] (clears needs_review for the current version)
 *
 * This slice is view + integrity-review only; creating a debt goal (which needs a
 * Debt picker) lands with the broader debt-management UI in a later slice.
 */
data class DebtGoalUiState(
    val isLoading: Boolean = false,
    val canModify: Boolean = true,
    val goals: List<Goal> = emptyList(),
    /** Non-null = the detail page for this goal is open; null = the list. */
    val selectedGoal: Goal? = null,
    val isSubmitting: Boolean = false,
    val error: UiText? = null,
    val flashMessage: UiText? = null,
)

class DebtGoalViewModel(
    private val repository: ReportsActions,
) : ViewModel() {

    private val _state = MutableStateFlow(DebtGoalUiState(canModify = repository.canModifyLedger()))
    val state: StateFlow<DebtGoalUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    /**
     * Clear any prior ledger's debt goals, then reload. Called whenever the overlay
     * (re-)opens (the VM is cached across the overlay's open/close and survives a
     * ledger switch in Settings), so the previous ledger's debt links — which carry
     * counterparties and amounts — never linger under a new ledger (ledger-isolation
     * boundary). Clearing up front avoids briefly showing stale cross-ledger data.
     */
    fun reload() {
        _state.update {
            it.copy(goals = emptyList(), selectedGoal = null, error = null, flashMessage = null)
        }
        refresh()
    }

    fun refresh() {
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            repository.debtGoals().fold(
                onSuccess = { goals ->
                    _state.update { current ->
                        current.copy(
                            isLoading = false,
                            canModify = repository.canModifyLedger(),
                            goals = goals,
                            // Keep an open detail in sync with the refreshed list.
                            selectedGoal = current.selectedGoal?.let { sel ->
                                goals.firstOrNull { it.publicId == sel.publicId } ?: sel
                            },
                            error = null,
                        )
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(isLoading = false, error = err.toUiText(R.string.debt_goal_load_failed))
                    }
                },
            )
        }
    }

    /**
     * Open the detail page. Selects optimistically from the list copy, then re-fetches
     * the single goal: a writer GET latches achievement server-side (ADR-0049 §6), so
     * opening the detail is the trigger. A failed re-fetch keeps the list copy.
     */
    fun openDetail(goal: Goal) {
        _state.update { it.copy(selectedGoal = goal) }
        viewModelScope.launch {
            repository.goal(goal.publicId).onSuccess { fresh ->
                _state.update { current ->
                    if (current.selectedGoal?.publicId == fresh.publicId) {
                        current.copy(selectedGoal = fresh, goals = current.goals.replaceGoal(fresh))
                    } else {
                        current
                    }
                }
            }
        }
    }

    fun closeDetail() {
        _state.update { it.copy(selectedGoal = null, error = null) }
    }

    /** §6/F13 exit (a): drop the debt-voided link(s) → a new goal version. */
    fun removeVoidedDebts() {
        val goal = _state.value.selectedGoal ?: return
        val evaluation = goal.debtRepayment ?: return
        val keep = evaluation.nonVoidedDebtPublicIds
        if (keep.isEmpty()) {
            // A debt goal must keep ≥1 link; every link voided has no clean replacement.
            _state.update { it.copy(error = UiText.res(R.string.debt_goal_remove_voided_needs_one)) }
            return
        }
        _state.update { it.copy(isSubmitting = true, error = null) }
        viewModelScope.launch {
            val result = repository.replaceDebtLinks(goal.publicId, goal.rowVersion, keep)
            applyMutation(result, R.string.debt_goal_links_updated)
        }
    }

    /** §6/F13 exit (b): acknowledge ("keep for audit") → clears needs_review. */
    fun acknowledge() {
        val goal = _state.value.selectedGoal ?: return
        _state.update { it.copy(isSubmitting = true, error = null) }
        viewModelScope.launch {
            val result = repository.acknowledgeDebtIntegrityReview(goal.publicId, goal.rowVersion)
            applyMutation(result, R.string.debt_goal_review_acknowledged)
        }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }

    private fun applyMutation(result: Result<Goal>, successRes: Int) {
        result.fold(
            onSuccess = { updated ->
                _state.update { current ->
                    current.copy(
                        isSubmitting = false,
                        selectedGoal = updated,
                        goals = current.goals.replaceGoal(updated),
                        flashMessage = UiText.res(successRes),
                        error = null,
                    )
                }
            },
            onFailure = { err ->
                _state.update {
                    it.copy(isSubmitting = false, error = err.toUiText(R.string.debt_goal_update_failed))
                }
            },
        )
    }
}

private fun List<Goal>.replaceGoal(updated: Goal): List<Goal> =
    map { if (it.publicId == updated.publicId) updated else it }
