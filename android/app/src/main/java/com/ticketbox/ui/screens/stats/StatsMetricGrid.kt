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
import androidx.compose.foundation.layout.width
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
                    // 轴3 bullet:百分比改报真实占比(此前 progress 截断在 1,超支永远显示
                    // 100%——既然条已能表达超出段,数字也要跟上)。
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
}

/**
 * 轴3 bullet 预算条。未超支=现状语义(轨道上限=预算,实际条到 progress);
 * 超支=轨道上限改为**实际支出**:先整条铺 warning(超出段),再从左覆盖 primary 到
 * 预算刻度位([budgetTickFraction]),刻度竖线标出预算所在——一眼读出「超了多少」,
 * 而非旧版整条变色只报「超了」。纯 Box 叠层,零图表依赖(Vico 无横向条)。
 */
@Composable
private fun BudgetBulletBar(budget: BudgetProgress) {
    val visuals = LocalThemeVisuals.current
    val tick = budgetTickFraction(budget)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(7.dp)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.10f)),
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

/**
 * 轴3 bullet:超支时预算刻度在「以实际支出为轨道上限」的条上的位置(budget/spent);
 * 未超支(或数据不可用)返回 null=走普通进度条。纯函数,单测直测。
 */
internal fun budgetTickFraction(budget: BudgetProgress): Float? {
    if (!budget.overBudget) return null
    if (budget.budgetCents <= 0L || budget.spentCents <= 0L) return null
    if (budget.spentCents <= budget.budgetCents) return null
    return (budget.budgetCents.toFloat() / budget.spentCents.toFloat()).coerceIn(0f, 1f)
}

/**
 * 真实支出占预算百分比(spent*100/budget,可 >100)。预算不可用时退回截断版
 * progress 百分比(与旧行为一致,绝不除零)。
 */
internal fun budgetSpentPercent(budget: BudgetProgress): Int {
    if (budget.budgetCents <= 0L) return (budget.progress.coerceIn(0f, 1f) * 100).toInt()
    return ((budget.spentCents * 100) / budget.budgetCents).toInt()
}
