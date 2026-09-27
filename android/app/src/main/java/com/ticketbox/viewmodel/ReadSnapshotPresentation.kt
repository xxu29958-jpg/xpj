package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.BudgetMonthly

/** A recovered command receipt retires older queries, never a query already at that revision. */
internal fun BudgetMonthly?.isOlderThanAccepted(receipt: BudgetMonthly?): Boolean =
    receipt?.rowVersion == null || (this?.rowVersion ?: 0L) < receipt.rowVersion

internal fun Throwable.isReadAccessDenied(): Boolean =
    (this as? RepositoryException)?.httpStatusCode in setOf(401, 403)

internal fun BudgetUiState.withReadFailure(error: Throwable): BudgetUiState {
    val denied = error.isReadAccessDenied()
    val visible = budget.takeUnless { denied }
    return copy(loading = false, budget = visible, fetchedAt = fetchedAt.takeUnless { denied },
        fromCache = !denied && fromCache,
        form = if (!denied || formDirty) form else saves.firstOrNull {
            it.row.status != PendingMutationStatus.Done
        }?.originalForm() ?: BudgetFormState(),
        loadError = error.toUiText(if (visible == null) com.ticketbox.R.string.budget_message_load_failed
            else com.ticketbox.R.string.budget_message_refresh_failed_with_data))
}

internal fun DebtGoalUiState.withReadFailure(error: Throwable): DebtGoalUiState {
    val denied = error.isReadAccessDenied()
    return copy(isLoading = false, error = error.toUiText(com.ticketbox.R.string.debt_goal_load_failed),
        goals = if (denied) emptyList() else goals, selectedGoal = if (denied) null else selectedGoal,
        fetchedAt = if (denied) null else fetchedAt, fromCache = !denied && fromCache,
        selectedFetchedAt = if (denied) null else selectedFetchedAt,
        selectedFromCache = !denied && selectedFromCache)
}

internal fun SpendingGoalDetailUiState.withReadFailure(error: Throwable): SpendingGoalDetailUiState {
    val denied = error.isReadAccessDenied()
    return copy(isLoading = false, loadError = error.toUiText(com.ticketbox.R.string.spending_goal_detail_load_failed),
        goal = if (denied) null else goal, fetchedAt = if (denied) null else fetchedAt,
        fromCache = !denied && fromCache)
}

internal fun StatsReportsUiState.withGoalRead(result: Result<com.ticketbox.data.repository.ReadSnapshot<List<com.ticketbox.domain.model.Goal>>>): StatsReportsUiState {
    val read = result.getOrNull()
    val denied = result.exceptionOrNull()?.isReadAccessDenied() == true
    return copy(reportGoals = read?.value ?: if (denied) emptyList() else reportGoals,
        reportGoalsFetchedAt = read?.fetchedAt ?: if (denied) null else reportGoalsFetchedAt,
        reportGoalsFromCache = read?.fromCache ?: (!denied && reportGoalsFromCache),
        reportGoalsLoadState = if (result.isSuccess) ReportGoalsLoadState.Loaded else ReportGoalsLoadState.Failed)
}
