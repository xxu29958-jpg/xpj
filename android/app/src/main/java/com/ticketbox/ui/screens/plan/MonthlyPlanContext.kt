package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetAdviceInputs
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun MonthlyPlanBudget(inputs: BudgetAdviceInputs, onOpenBudget: (() -> Unit)?) {
    var expanded by remember(inputs.month) { mutableStateOf(false) }
    val budget = inputs.budgetDefinition
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Text(stringResource(R.string.arrangement_budget_title), style = MaterialTheme.typography.titleMedium)
        if (budget == null) Text(stringResource(if (inputs.dataScope == null)
            R.string.arrangement_budget_unknown else R.string.arrangement_budget_unset))
        else {
            val currencyCode = budget.homeCurrencyCode ?: stringResource(R.string.spending_goal_currency_unknown)
            val currency = CurrencyDisplay.forRecord(currencyCode)
            AppAmountText(formatDisplayAmount(budget.totalAmountCents, currency), role = AppAmountRole.Medium)
            Text(stringResource(R.string.arrangement_budget_currency, currencyCode), style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = { expanded = !expanded }) {
                Text(stringResource(R.string.arrangement_budget_version))
            }
            if (expanded) {
                Text(stringResource(R.string.arrangement_budget_scope,
                    formatDisplayAmount(budget.rolloverAmountCents, currency),
                    formatDisplayAmount(budget.nonMonthlyAmountCents, currency)))
                if (budget.excludedCategories.isNotEmpty()) Text(stringResource(R.string.arrangement_budget_excluded,
                    budget.excludedCategories.joinToString("、")))
            }
        }
        onOpenBudget?.let { TextButton(onClick = it) { Text(stringResource(R.string.arrangement_budget_open)) } }
    }
}

@Composable
internal fun MonthlyPlanExplanation(inputs: BudgetAdviceInputs) {
    if (inputs.plannedTotalCents != null) {
        Text(stringResource(R.string.arrangement_plan_total,
            formatDisplayAmount(inputs.plannedTotalCents, CurrencyDisplay.forRecord(inputs.homeCurrencyCode)), inputs.homeCurrencyCode))
    } else if (inputs.budgetDefinition != null) Text(stringResource(R.string.arrangement_plan_separate))
    Text(stringResource(R.string.arrangement_plan_explanation))
}

@Composable
internal fun BudgetAdviceDataScope(inputs: BudgetAdviceInputs) {
    val scope = inputs.dataScope
    if (scope == null) Text(stringResource(R.string.advice_scope_unknown), style = MaterialTheme.typography.bodySmall)
    else Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Text(stringResource(R.string.advice_scope_current, displayMonthLabel(inputs.month), displayTime(scope.readAt)),
            style = MaterialTheme.typography.bodySmall)
        Text(stringResource(R.string.advice_scope_history, scope.historyFromMonth, scope.historyToMonth, scope.historyCategoryCount),
            style = MaterialTheme.typography.bodySmall)
    }
}
