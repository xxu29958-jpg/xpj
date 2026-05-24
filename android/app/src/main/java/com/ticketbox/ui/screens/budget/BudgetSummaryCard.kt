package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.SkeletonBlock
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.valentinilk.shimmer.shimmer

@Composable
internal fun BudgetSummaryCard(
    budget: BudgetMonthly?,
    loading: Boolean,
    currencyDisplay: CurrencyDisplay,
) {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
        ) {
            BudgetSummaryTitle(budget)
            if (budget == null) {
                BudgetSummaryPlaceholder(loading)
                return@Column
            }
            BudgetProgressBar(progress = budget.spentProgress)
            BudgetMetricRows(
                budget = budget,
                currencyDisplay = currencyDisplay,
            )
        }
    }
}

@Composable
private fun BudgetSummaryTitle(budget: BudgetMonthly?) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
    ) {
        Text(
            text = "本月预算",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = if (budget?.configured == true) "${budget.spentPercent}%" else "未配置",
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
            SkeletonBlock(modifier = Modifier.fillMaxWidth(0.8f).height(22.dp))
            SkeletonBlock(modifier = Modifier.fillMaxWidth().height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                SkeletonBlock(modifier = Modifier.weight(1f).height(58.dp))
                SkeletonBlock(modifier = Modifier.weight(1f).height(58.dp))
            }
        }
        return
    }
    Text(
        text = "正在读取预算。",
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
            label = "总额",
            value = formatDisplayAmount(budget.availableAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
        MetricPill(
            label = if (budget.isOverBudget) "超支" else "剩余",
            value = formatDisplayAmount(
                if (budget.isOverBudget) budget.overspentAmountCents else budget.remainingAmountCents,
                currencyDisplay,
            ),
            modifier = Modifier.weight(1f),
        )
    }
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        MetricPill(
            label = "已花",
            value = formatDisplayAmount(budget.spentAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
        MetricPill(
            label = "灵活可花",
            value = formatDisplayAmount(budget.flexBudgetCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
    }
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        MetricPill(
            label = "固定支出",
            value = formatDisplayAmount(budget.fixedAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
        MetricPill(
            label = "剔除",
            value = formatDisplayAmount(budget.excludedAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
    }
}
