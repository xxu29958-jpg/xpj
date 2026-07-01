package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.SkeletonBlock
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.valentinilk.shimmer.shimmer

@Composable
internal fun BudgetSummarySection(
    budget: BudgetMonthly?,
    loading: Boolean,
    loadError: UiText?,
    currencyDisplay: CurrencyDisplay,
    onRetry: () -> Unit,
) {
    // A failed load with no budget gets a retryable error state instead of the card
    // (审计 8.4)——otherwise the placeholder's "正在读取预算。" loading copy stays forever.
    if (budget == null && !loading && loadError != null) {
        AppErrorState(
            title = stringResource(R.string.budget_summary_error_title),
            body = loadError.asString().ifBlank { stringResource(R.string.budget_summary_error_body) },
            onRetry = onRetry,
        )
        return
    }
    val configuredBudget = budget?.takeIf { it.configured }
    BudgetOpenSection(
        title = stringResource(R.string.budget_summary_title),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        BudgetSummaryStatus(configuredBudget)
        if (configuredBudget == null) {
            BudgetSummaryPlaceholder(loading)
            return@BudgetOpenSection
        }
        BudgetProgressBar(progress = configuredBudget.spentProgress)
        BudgetMetricRows(
            budget = configuredBudget,
            currencyDisplay = currencyDisplay,
        )
    }
}

@Composable
private fun BudgetSummaryStatus(budget: BudgetMonthly?) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(R.string.budget_summary_status_label),
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = if (budget?.configured == true) {
                stringResource(R.string.budget_summary_percent, budget.spentPercent)
            } else {
                stringResource(R.string.budget_summary_unconfigured)
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
        )
    }
}

@Composable
private fun BudgetSummaryPlaceholder(loading: Boolean) {
    if (loading) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .shimmer(),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            SkeletonBlock(modifier = Modifier.fillMaxWidth(0.8f).height(AppSpacing.cardPadding + AppSpacing.tinyGap))
            SkeletonBlock(modifier = Modifier.fillMaxWidth().height(AppSpacing.compactGap))
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                SkeletonBlock(modifier = Modifier.weight(1f).height(AppSpacing.controlMinHeight + AppSpacing.cardPaddingSmall))
                SkeletonBlock(modifier = Modifier.weight(1f).height(AppSpacing.controlMinHeight + AppSpacing.cardPaddingSmall))
            }
        }
        return
    }
    Text(
        text = stringResource(R.string.budget_summary_unconfigured_body),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodyMedium,
    )
}

@Composable
private fun BudgetMetricRows(
    budget: BudgetMonthly,
    currencyDisplay: CurrencyDisplay,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        MetricPill(
            label = stringResource(R.string.budget_summary_metric_total),
            value = formatDisplayAmount(budget.availableAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
        MetricPill(
            label = if (budget.isOverBudget) {
                stringResource(R.string.budget_summary_metric_overspent)
            } else {
                stringResource(R.string.budget_summary_metric_remaining)
            },
            value = formatDisplayAmount(
                if (budget.isOverBudget) budget.overspentAmountCents else budget.remainingAmountCents,
                currencyDisplay,
            ),
            modifier = Modifier.weight(1f),
        )
    }
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        MetricPill(
            label = stringResource(R.string.budget_summary_metric_spent),
            value = formatDisplayAmount(budget.spentAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
        MetricPill(
            label = stringResource(R.string.budget_summary_metric_flex),
            value = formatDisplayAmount(budget.flexBudgetCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
    }
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        MetricPill(
            label = stringResource(R.string.budget_summary_metric_fixed),
            value = formatDisplayAmount(budget.fixedAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
        MetricPill(
            label = stringResource(R.string.budget_summary_metric_excluded),
            value = formatDisplayAmount(budget.excludedAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
    }
}
