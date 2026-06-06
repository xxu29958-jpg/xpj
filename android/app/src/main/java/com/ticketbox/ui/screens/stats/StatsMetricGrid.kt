package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
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
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals

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
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
            StatsMetricCard(
                modifier = Modifier.weight(1f),
                label = stringResource(R.string.stats_metric_ai_subscription_label),
                value = lifestyle?.aiSubscriptionAmountCents?.takeIf { it > 0L }?.let { formatDisplayAmount(it, currencyDisplay) }
                    ?: aiCategoryAmount?.let { formatDisplayAmount(it, currencyDisplay) }
                    ?: emptyValue,
                accent = 0,
            )
            StatsMetricCard(
                modifier = Modifier.weight(1f),
                label = stringResource(R.string.stats_metric_max_expense_label),
                value = lifestyle?.maxExpense?.amountCents?.let { formatDisplayAmount(it, currencyDisplay) } ?: emptyValue,
                caption = lifestyle?.maxExpense?.merchant?.takeIf { it.isNotBlank() },
                accent = 1,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
            StatsMetricCard(
                modifier = Modifier.weight(1f),
                label = stringResource(R.string.stats_metric_frequent_merchant_label),
                value = frequentMerchant?.merchant ?: emptyValue,
                caption = frequentMerchantCaption,
                accent = 2,
            )
            StatsMetricCard(
                modifier = Modifier.weight(1f),
                label = stringResource(R.string.stats_metric_category_concentration_label),
                value = concentrationValue,
                caption = concentrationCaption,
                accent = 3,
            )
        }
        budget?.let { BudgetProgressCard(it, currencyDisplay) }
    }
}

@Composable
private fun BudgetProgressCard(
    budget: BudgetProgress,
    currencyDisplay: CurrencyDisplay,
) {
    val visuals = LocalThemeVisuals.current
    val progress = budget.progress.coerceIn(0f, 1f)
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingTight),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
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
                    text = stringResource(R.string.stats_budget_progress_percent, (progress * 100).toInt()),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontWeight = AppTextHierarchy.body.weight,
                )
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(7.dp)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.10f)),
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(progress)
                        .height(7.dp)
                        .clip(RoundedCornerShape(AppRadius.pill))
                        .background(if (budget.overBudget) visuals.warningTint else visuals.primary),
                )
            }
            Text(
                text = stringResource(R.string.stats_budget_progress_hint),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun StatsMetricCard(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    caption: String? = null,
    accent: Int = 0,
) {
    val visuals = LocalThemeVisuals.current
    val isEmptyValue = value == stringResource(R.string.stats_metric_empty_value)
    val accentColors = listOf(
        visuals.chipSelected,
        visuals.warningTint.copy(alpha = 0.28f),
        visuals.glassTint.copy(alpha = 0.88f),
        visuals.shadowTint.copy(alpha = 0.12f),
    )
    AppGlassCard(modifier = modifier, containerAlpha = 0.96f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingTight),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap), verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(22.dp)
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
                Text(
                    text = label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                    maxLines = 1,
                )
            }
            Text(
                text = value,
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
            caption?.let {
                Text(
                    text = it,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}
