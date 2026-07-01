package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetProgress
import com.ticketbox.domain.model.CategoryInsight
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals

private data class StatsInsightMetric(
    val label: String,
    val value: String,
    val caption: String? = null,
    val accent: Int = 0,
)

@Composable
internal fun StatsMetricGrid(
    stats: MonthlyStats,
    lifestyle: LifestyleStats?,
    insight: CategoryInsight?,
    budget: BudgetProgress?,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val aiCategoryAmount = stats.byCategory
        .firstOrNull { it.category == "AI订阅" || it.category == "AI 订阅" }
        ?.amountCents
        ?.takeIf { it > 0L }
    val emptyValue = stringResource(R.string.stats_metric_empty_value)
    val frequentMerchant = lifestyle?.frequentMerchants?.firstOrNull()
    val frequentMerchantCaption = frequentMerchant?.let {
        stringResource(R.string.stats_metric_merchant_count, it.count)
    }
    val concentrationValue = insight?.topCategory
        ?: stringResource(R.string.stats_metric_category_count, stats.byCategory.count { it.amountCents > 0L })
    val concentrationCaption = insight?.let {
        stringResource(R.string.stats_metric_top_share, it.topSharePercent)
    }
    val metrics = listOf(
        StatsInsightMetric(
            label = stringResource(R.string.stats_metric_ai_subscription_label),
            value = lifestyle?.aiSubscriptionAmountCents?.takeIf { it > 0L }?.let { formatDisplayAmount(it, currencyDisplay) }
                ?: aiCategoryAmount?.let { formatDisplayAmount(it, currencyDisplay) }
                ?: emptyValue,
            accent = 0,
        ),
        StatsInsightMetric(
            label = stringResource(R.string.stats_metric_max_expense_label),
            value = lifestyle?.maxExpense?.amountCents?.let { formatDisplayAmount(it, currencyDisplay) } ?: emptyValue,
            caption = lifestyle?.maxExpense?.merchant?.takeIf { it.isNotBlank() },
            accent = 1,
        ),
        StatsInsightMetric(
            label = stringResource(R.string.stats_metric_frequent_merchant_label),
            value = frequentMerchant?.merchant ?: emptyValue,
            caption = frequentMerchantCaption,
            accent = 2,
        ),
        StatsInsightMetric(
            label = stringResource(R.string.stats_metric_category_concentration_label),
            value = concentrationValue,
            caption = concentrationCaption,
            accent = 3,
        ),
    )
    val visuals = LocalThemeVisuals.current

    StatsInsightSurface {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Text(
                text = stringResource(R.string.stats_metric_module_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            MonthlyInsightRows(metrics = metrics, emptyValue = emptyValue)
            budget?.let {
                HorizontalDivider(color = visuals.chipUnselected.copy(alpha = AppAlpha.soft))
                BudgetProgressSection(it, currencyDisplay)
            }
        }
    }
}

@Composable
private fun MonthlyInsightRows(
    metrics: List<StatsInsightMetric>,
    emptyValue: String,
) {
    val visuals = LocalThemeVisuals.current
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        metrics.forEachIndexed { index, metric ->
            if (index > 0) {
                HorizontalDivider(color = visuals.chipUnselected.copy(alpha = AppAlpha.subtle))
            }
            StatsInsightMetricRow(metric = metric, emptyValue = emptyValue)
        }
    }
}

@Composable
private fun StatsInsightMetricRow(
    metric: StatsInsightMetric,
    emptyValue: String,
) {
    val isEmptyValue = metric.value == emptyValue
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MetricAccentMark(accent = metric.accent)
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = metric.label,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            metric.caption?.let {
                Text(
                    text = it,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Text(
            text = metric.value,
            color = if (isEmptyValue) {
                MaterialTheme.colorScheme.onSurfaceVariant
            } else {
                MaterialTheme.colorScheme.onSurface
            },
            style = if (isEmptyValue) {
                MaterialTheme.typography.titleSmall
            } else {
                MaterialTheme.typography.titleMedium
            },
            fontWeight = if (isEmptyValue) AppTextHierarchy.caption.weight else AppTextHierarchy.body.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun MetricAccentMark(accent: Int) {
    val visuals = LocalThemeVisuals.current
    val accentColors = listOf(
        visuals.chipSelected,
        visuals.warningTint.copy(alpha = AppAlpha.soft),
        visuals.glassTint.copy(alpha = AppAlpha.opaque),
        visuals.shadowTint.copy(alpha = AppAlpha.subtle),
    )
    Box(
        modifier = Modifier
            .size(18.dp)
            .clip(RoundedCornerShape(AppRadius.extraSmall))
            .background(accentColors[accent % accentColors.size]),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(5.dp)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(visuals.primary),
        )
    }
}

@Composable
private fun BudgetProgressSection(
    budget: BudgetProgress,
    currencyDisplay: CurrencyDisplay,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(
                    stringResource(R.string.stats_budget_progress_title),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = if (budget.overBudget) {
                        stringResource(R.string.stats_budget_progress_over)
                    } else {
                        stringResource(
                            R.string.stats_budget_progress_remaining,
                            formatDisplayAmount(budget.remainingCents, currencyDisplay),
                        )
                    },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
            }
            Text(
                text = stringResource(R.string.stats_budget_progress_percent, budgetSpentPercent(budget)),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontWeight = AppTextHierarchy.body.weight,
            )
        }
        BudgetBulletBar(budget)
        Text(
            text = stringResource(R.string.stats_budget_progress_hint),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun BudgetBulletBar(budget: BudgetProgress) {
    val visuals = LocalThemeVisuals.current
    val tick = budgetTickFraction(budget)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(7.dp)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.faint)),
    ) {
        if (tick == null) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(budget.progress.coerceIn(0f, 1f))
                    .height(7.dp)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(visuals.primary),
            )
        } else {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(7.dp)
                    .background(visuals.warningTint),
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth(tick)
                    .height(7.dp)
                    .background(visuals.primary),
            )
            Row(modifier = Modifier.fillMaxWidth()) {
                if (tick > 0f) {
                    Box(modifier = Modifier.weight(tick))
                }
                Box(
                    modifier = Modifier
                        .width(2.dp)
                        .height(7.dp)
                        .background(MaterialTheme.colorScheme.onSurface),
                )
                if (tick < 1f) {
                    Box(modifier = Modifier.weight(1f - tick))
                }
            }
        }
    }
}

internal fun budgetTickFraction(budget: BudgetProgress): Float? {
    if (!budget.overBudget) return null
    if (budget.budgetCents <= 0L || budget.spentCents <= 0L) return null
    if (budget.spentCents <= budget.budgetCents) return null
    return (budget.budgetCents.toFloat() / budget.spentCents.toFloat()).coerceIn(0f, 1f)
}

internal fun budgetSpentPercent(budget: BudgetProgress): Int {
    if (budget.budgetCents <= 0L) return (budget.progress.coerceIn(0f, 1f) * 100).toInt()
    return ((budget.spentCents * 100) / budget.budgetCents).toInt()
}
