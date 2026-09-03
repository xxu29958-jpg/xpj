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
import com.ticketbox.ui.components.AppAdaptiveMetricGrid
import com.ticketbox.ui.components.AppAdaptiveMetricGridCompactMinWidth
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.SkeletonBlock
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalStateTokens
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
        BudgetSummaryHero(
            budget = configuredBudget,
            currencyDisplay = currencyDisplay,
        )
        BudgetProgressBar(progress = configuredBudget.spentProgress)
        BudgetMetricRows(
            budget = configuredBudget,
            currencyDisplay = currencyDisplay,
        )
    }
}

@Composable
private fun BudgetSummaryHero(
    budget: BudgetMonthly,
    currencyDisplay: CurrencyDisplay,
) {
    val label = stringResource(
        if (budget.isOverBudget) R.string.budget_summary_metric_overspent else R.string.budget_summary_metric_remaining,
    )
    val value = formatDisplayAmount(
        if (budget.isOverBudget) budget.overspentAmountCents else budget.remainingAmountCents,
        currencyDisplay,
    )
    val amountColor = if (budget.isOverBudget) {
        LocalStateTokens.current.danger.fg
    } else {
        MaterialTheme.colorScheme.onSurface
    }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
        )
        AppAmountText(
            text = value,
            role = AppAmountRole.Hero,
            color = amountColor,
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
            AppAdaptiveMetricGrid(
                itemCount = BUDGET_SUMMARY_PLACEHOLDER_METRICS,
                twoColumnMinWidth = AppAdaptiveMetricGridCompactMinWidth,
            ) { _, metricModifier ->
                SkeletonBlock(
                    modifier = metricModifier.height(AppSpacing.controlMinHeight + AppSpacing.cardPaddingSmall),
                )
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
    val metrics = listOf(
        stringResource(R.string.budget_summary_metric_total) to
            formatDisplayAmount(budget.availableAmountCents, currencyDisplay),
        stringResource(R.string.budget_summary_metric_spent) to
            formatDisplayAmount(budget.spentAmountCents, currencyDisplay),
        stringResource(R.string.budget_summary_metric_flex) to
            formatDisplayAmount(budget.flexBudgetCents, currencyDisplay),
        stringResource(R.string.budget_summary_metric_fixed) to
            formatDisplayAmount(budget.fixedAmountCents, currencyDisplay),
        stringResource(R.string.budget_summary_metric_excluded) to
            formatDisplayAmount(budget.excludedAmountCents, currencyDisplay),
    )
    AppAdaptiveMetricGrid(
        itemCount = metrics.size,
        twoColumnMinWidth = AppAdaptiveMetricGridCompactMinWidth,
    ) { index, metricModifier ->
        val (label, value) = metrics[index]
        MetricPill(
            label = label,
            value = value,
            modifier = metricModifier,
        )
    }
}

private const val BUDGET_SUMMARY_PLACEHOLDER_METRICS = 2
