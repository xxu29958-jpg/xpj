package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppContentStateCopy
import com.ticketbox.ui.components.AppContentStateSpec
import com.ticketbox.ui.components.AppContentStateSlot
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppLoadingState
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.budget.MonthSwitcher
import com.ticketbox.viewmodel.SpendingGoalsUiState
import com.ticketbox.viewmodel.SpendingGoalsViewModel

internal data class SpendingGoalsScreenActions(
    val onBack: () -> Unit,
    val onCreate: () -> Unit,
    val onOpenGoal: (String) -> Unit,
)

@Composable
internal fun SpendingGoalsScreen(
    viewModel: SpendingGoalsViewModel,
    actions: SpendingGoalsScreenActions,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.spending_goals_page_title),
            subtitle = stringResource(
                R.string.spending_goals_page_subtitle,
                displayMonthLabel(state.month),
            ),
            backText = stringResource(R.string.spending_goals_back_to_plan),
            onBack = actions.onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = state.isLoading,
            onRefresh = viewModel::refresh,
        ),
        slots = AppSecondaryPageSlots(
            status = { SpendingGoalsStatus(state) },
            bottomBar = if (state.canModify) {
                { SpendingGoalsFooter(actions.onCreate) }
            } else {
                null
            },
        ),
    ) {
        item {
            MonthSwitcher(
                month = displayMonthLabel(state.month),
                onPreviousMonth = viewModel::previousMonth,
                onNextMonth = viewModel::nextMonth,
            )
        }
        item {
            SpendingGoalsBody(
                state = state,
                onRetry = viewModel::refresh,
                onOpenGoal = actions.onOpenGoal,
            )
        }
    }
}

@Composable
private fun SpendingGoalsStatus(state: SpendingGoalsUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        AppDataAuthorityStrip(
            tone = when {
                !state.canModify -> DataAuthorityTone.ReadOnly
                state.isLoading -> DataAuthorityTone.Refreshing
                else -> DataAuthorityTone.Backend
            },
        )
        if (!state.canModify) {
            AppStatusBanner(
                message = UiText.res(R.string.common_readonly_ledger),
                tone = MessageTone.Info,
                announceUpdates = false,
            )
        }
        if (state.goals.isNotEmpty()) {
            state.loadError?.let {
                AppStatusBanner(message = it, tone = MessageTone.Danger)
            }
        }
    }
}

@Composable
private fun SpendingGoalsBody(
    state: SpendingGoalsUiState,
    onRetry: () -> Unit,
    onOpenGoal: (String) -> Unit,
) {
    when {
        state.isLoading && state.goals.isEmpty() -> AppLoadingState(
            title = stringResource(R.string.spending_goals_loading_title),
            body = stringResource(R.string.spending_goals_loading_body),
        )
        state.loadError != null && state.goals.isEmpty() -> AppErrorState(
            title = stringResource(R.string.spending_goals_error_title),
            body = state.loadError.asString().ifBlank {
                stringResource(R.string.spending_goals_load_failed)
            },
            onRetry = onRetry,
        )
        state.goals.isEmpty() -> AppContentStateSlot(
            state = AppContentStateSpec(
                loading = false,
                hasData = false,
                copy = AppContentStateCopy(
                    loadingTitle = stringResource(R.string.spending_goals_loading_title),
                    emptyText = stringResource(R.string.spending_goals_empty_body),
                    emptyTitle = stringResource(R.string.spending_goals_empty_title),
                    emptyBody = stringResource(R.string.spending_goals_empty_body),
                ),
            ),
        )
        else -> SpendingGoalListCard(
            goals = state.goals,
            onOpenGoal = onOpenGoal,
        )
    }
}

@Composable
private fun SpendingGoalsFooter(onCreate: () -> Unit) {
    AppFloatingActionBar {
        AppPrimaryButton(
            text = stringResource(R.string.spending_goals_create_action),
            icon = Icons.Filled.Add,
            modifier = Modifier.fillMaxWidth(),
            onClick = onCreate,
        )
    }
}
