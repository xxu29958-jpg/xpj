package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepositoryException

internal fun Throwable.isReadAccessDenied(): Boolean =
    (this as? RepositoryException)?.httpStatusCode in setOf(401, 403)

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
