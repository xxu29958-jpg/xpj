package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptivePaneScaffold
import com.ticketbox.ui.components.AppAdaptivePanePurpose
import com.ticketbox.ui.components.AppAdaptivePaneStructures
import com.ticketbox.ui.components.AppAdaptiveSupportingPane
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppScrollableContentChrome
import com.ticketbox.ui.components.AppScrollableContentLayout
import com.ticketbox.ui.components.AppScrollableRefreshState
import com.ticketbox.ui.components.appAdaptiveSupportingPaneContent
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.viewmodel.BudgetUiState
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.RecurringUiState

internal object PlanDestinationTestTags {
    const val Budget = "plan_destination_budget"
    const val BudgetAdvice = "plan_destination_budget_advice"
    const val SpendingGoal = "plan_destination_spending_goal"
    const val Recurring = "plan_destination_recurring"
    const val IncomePlans = "plan_destination_income_plans"
}

internal data class PlanScreenData(
    val budget: BudgetUiState,
    val recurring: RecurringUiState,
    val income: IncomePlanUiState,
) {
    val refreshing: Boolean
        get() = budget.loading || recurring.loading || income.isLoading
}

internal data class PlanBudgetNavigationActions(
    val onOpenBudget: () -> Unit,
    val onOpenAdvice: () -> Unit,
)

internal data class PlanScreenActions(
    val budgetNavigation: PlanBudgetNavigationActions,
    val onOpenSpendingGoal: () -> Unit,
    val onOpenRecurring: () -> Unit,
    val onOpenIncomePlans: () -> Unit,
    val onRefresh: () -> Unit,
)

@Composable
internal fun PlanScreen(
    data: PlanScreenData,
    actions: PlanScreenActions,
) {
    val adaptivePolicy = LocalAppAdaptiveLayoutPolicy.current
    AppAdaptivePaneScaffold(
        structure = AppAdaptivePaneStructures.Plans,
        policy = adaptivePolicy,
        primaryPane = {
            PlanPrimaryPane(
                data = data,
                actions = actions,
                showSupportingPane = adaptivePolicy.showsSupportingPane,
            )
        },
        supportingPane = appAdaptiveSupportingPaneContent(
            purpose = AppAdaptivePanePurpose.FixedArrangements,
        ) {
            AppAdaptiveSupportingPane(role = AppPageRole.Stats) {
                PlanFixedArrangementsSection(
                    recurring = data.recurring,
                    income = data.income,
                    onOpenRecurring = actions.onOpenRecurring,
                    onOpenIncomePlans = actions.onOpenIncomePlans,
                )
            }
        },
    )
}

@Composable
private fun PlanPrimaryPane(
    data: PlanScreenData,
    actions: PlanScreenActions,
    showSupportingPane: Boolean,
) {
    AppScrollableContent(
        chrome = AppScrollableContentChrome(
            role = AppPageRole.Stats,
            layout = AppScrollableContentLayout(
                horizontalPadding = AppSpacing.cardPaddingSmall,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
            ),
        ),
        refresh = AppScrollableRefreshState(
            isRefreshing = data.refreshing,
            onRefresh = actions.onRefresh,
        ),
    ) {
        item {
            PlanProductHeader(
                month = data.budget.month,
            )
        }
        item {
            PlanBudgetSection(
                state = data.budget,
                actions = actions.budgetNavigation,
            )
        }
        item {
            PlanGoalsSection(
                onOpenSpendingGoal = actions.onOpenSpendingGoal,
            )
        }
        if (!showSupportingPane) {
            item {
                PlanFixedArrangementsSection(
                    recurring = data.recurring,
                    income = data.income,
                    onOpenRecurring = actions.onOpenRecurring,
                    onOpenIncomePlans = actions.onOpenIncomePlans,
                )
            }
        }
    }
}

@Composable
private fun PlanProductHeader(
    month: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.Top,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = stringResource(R.string.plan_page_title),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.displayMedium,
            )
            Text(
                text = stringResource(
                    R.string.plan_page_month_context,
                    displayMonthLabel(month),
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
