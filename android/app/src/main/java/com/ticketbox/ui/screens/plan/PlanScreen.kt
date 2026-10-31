package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
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
import com.ticketbox.viewmodel.SpendingGoalsUiState

internal object PlanDestinationTestTags {
    const val Budget = "plan_destination_budget"
    const val BudgetAdvice = "plan_destination_budget_advice"
    const val SpendingGoal = "plan_destination_spending_goal"
    const val DebtGoal = "plan_destination_debt_goal"
    const val Recurring = "plan_destination_recurring"
    const val IncomePlans = "plan_destination_income_plans"
}

internal data class PlanScreenData(
    val budget: BudgetUiState,
    val recurring: RecurringUiState,
    val income: IncomePlanUiState,
    val goals: SpendingGoalsUiState,
) {
    val refreshing: Boolean
        get() = budget.loading || recurring.loading || income.isLoading || goals.isLoading
}

internal data class PlanBudgetNavigationActions(
    val onOpenBudget: () -> Unit,
    val onOpenAdvice: () -> Unit,
)

internal data class PlanScreenActions(
    val budgetNavigation: PlanBudgetNavigationActions,
    val onOpenSpendingGoal: () -> Unit,
    val onOpenDebtGoal: () -> Unit,
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
            AppAdaptiveSupportingPane(
                role = AppPageRole.Stats,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
            ) {
                PlanFixedArrangementsSection(
                    recurring = data.recurring,
                    income = data.income,
                    onOpenRecurring = actions.onOpenRecurring,
                    onOpenIncomePlans = actions.onOpenIncomePlans,
                )
                PlanMonthlyArrangement(onOpenAdvice = actions.budgetNavigation.onOpenAdvice)
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
        // 先给状态（预算读数、下一笔固定支出、本月消费目标），再列各入口分组。
        item {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
            ) {
                PlanBudgetSection(
                    state = data.budget,
                    actions = actions.budgetNavigation,
                )
                PlanStatusCard(
                    recurring = data.recurring,
                    goals = data.goals,
                    onOpenRecurring = actions.onOpenRecurring,
                    onOpenSpendingGoal = actions.onOpenSpendingGoal,
                )
            }
        }
        if (!showSupportingPane) {
            item { PlanMonthlyArrangement(onOpenAdvice = actions.budgetNavigation.onOpenAdvice) }
        }
        item {
            PlanGoalsSection(
                onOpenSpendingGoal = actions.onOpenSpendingGoal,
                onOpenDebtGoal = actions.onOpenDebtGoal,
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

/** 窄窗在状态之后作为第一个入口分组；宽窗与固定安排同在辅助区。 */
@Composable
private fun PlanMonthlyArrangement(
    onOpenAdvice: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        PlanSectionTitle(stringResource(R.string.plan_section_monthly_arrangement))
        PlanDestinationRow(
            model = PlanRowModel(
                title = stringResource(R.string.plan_budget_advice_title),
                subtitle = stringResource(R.string.plan_budget_advice_subtitle),
                icon = R.drawable.ic_lucide_sliders_horizontal,
                testTag = PlanDestinationTestTags.BudgetAdvice,
                onClick = onOpenAdvice,
            ),
        )
    }
}

@Composable
private fun PlanProductHeader(
    month: String,
) {
    // shell 已承载「计划」一级标题，body 不再重复大字标题，只留当前月份口径。
    Text(
        text = stringResource(
            R.string.plan_page_month_context,
            displayMonthLabel(month),
        ),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodyMedium,
    )
}
