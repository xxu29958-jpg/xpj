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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.FrequentMerchant
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun LifestyleCard(lifestyle: LifestyleStats) {
    val visuals = LocalThemeVisuals.current
    val currencyDisplay = LocalCurrencyDisplay.current
    val hasSignals = hasLifestyleSignals(lifestyle)
    val hasMerchants = lifestyle.frequentMerchants.isNotEmpty()
    val hasValueRegret = lifestyle.bestValueExpenses.isNotEmpty() || lifestyle.mostRegrettedExpenses.isNotEmpty()

    StatsInsightSurface {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            LifestyleHeader(lifestyle = lifestyle, currencyDisplay = currencyDisplay)
            if (hasSignals) {
                LifestyleSignalSection(lifestyle = lifestyle, currencyDisplay = currencyDisplay)
            }
            if (hasSignals && (hasMerchants || hasValueRegret)) {
                HorizontalDivider(color = visuals.chipUnselected.copy(alpha = AppAlpha.heavy))
            }
            if (hasMerchants) {
                FrequentMerchantsSection(lifestyle.frequentMerchants)
            }
            if (hasMerchants && hasValueRegret) {
                HorizontalDivider(color = visuals.chipUnselected.copy(alpha = AppAlpha.heavy))
            }
            if (hasValueRegret) {
                ValueRegretSections(
                    bestValueExpenses = lifestyle.bestValueExpenses,
                    mostRegrettedExpenses = lifestyle.mostRegrettedExpenses,
                )
            }
        }
    }
}

@Composable
private fun LifestyleHeader(
    lifestyle: LifestyleStats,
    currencyDisplay: CurrencyDisplay,
) {
    val merchantFallback = stringResource(R.string.stats_lifestyle_merchant_fallback)
    val frequentMerchant = lifestyle.frequentMerchants.firstOrNull()
    val merchantCount = lifestyle.frequentMerchants.size
    val maxExpense = lifestyle.maxExpense
    val caption = when {
        frequentMerchant != null && frequentMerchant.count <= 1 && merchantCount > 1 -> stringResource(
            R.string.stats_lifestyle_header_merchant_spread,
            merchantCount,
        )
        frequentMerchant != null -> stringResource(
            R.string.stats_lifestyle_header_frequent,
            frequentMerchant.merchant.ifBlank { merchantFallback },
            frequentMerchant.count,
        )
        maxExpense != null -> stringResource(
            R.string.stats_lifestyle_header_largest,
            formatDisplayAmount(maxExpense.amountCents, currencyDisplay),
            maxExpense.merchant?.takeIf { it.isNotBlank() } ?: merchantFallback,
        )
        else -> stringResource(R.string.stats_lifestyle_empty)
    }

    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            text = stringResource(R.string.stats_lifestyle_module_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = caption,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun LifestyleSignalSection(
    lifestyle: LifestyleStats,
    currencyDisplay: CurrencyDisplay,
) {
    val merchantFallback = stringResource(R.string.stats_lifestyle_merchant_fallback)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        if (lifestyle.aiSubscriptionAmountCents > 0L) {
            LifestyleMetricRow(
                label = stringResource(R.string.stats_lifestyle_ai_subscription),
                value = formatDisplayAmount(lifestyle.aiSubscriptionAmountCents, currencyDisplay),
            )
        }
        if (lifestyle.digitalAmountCents > 0L) {
            LifestyleMetricRow(
                label = stringResource(R.string.stats_lifestyle_digital),
                value = formatDisplayAmount(lifestyle.digitalAmountCents, currencyDisplay),
            )
        }
        lifestyle.maxExpense?.let { maxExpense ->
            LifestyleMetricRow(
                label = stringResource(R.string.stats_lifestyle_max_expense),
                value = formatDisplayAmount(maxExpense.amountCents, currencyDisplay),
                caption = maxExpense.merchant?.takeIf { it.isNotBlank() } ?: merchantFallback,
            )
        }
    }
}

@Composable
private fun LifestyleMetricRow(
    label: String,
    value: String,
    caption: String? = null,
) {
    val visuals = LocalThemeVisuals.current
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(visuals.accent),
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            caption?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Text(
            text = value,
            style = MaterialTheme.typography.labelLarge.tabularNum(),
            color = MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
        )
    }
}

@Composable
private fun FrequentMerchantsSection(merchants: List<FrequentMerchant>) {
    val visuals = LocalThemeVisuals.current
    val visibleMerchants = merchants.take(5)
    val maxCount = visibleMerchants.maxOfOrNull { it.count }?.coerceAtLeast(1) ?: 1
    val minCount = visibleMerchants.minOfOrNull { it.count } ?: maxCount
    val showBars = maxCount > minCount
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(
            text = stringResource(R.string.stats_frequent_merchants_title),
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        visibleMerchants.forEachIndexed { index, merchant ->
            if (index > 0) {
                HorizontalDivider(color = visuals.chipUnselected.copy(alpha = AppAlpha.soft))
            }
            FrequentMerchantRow(
                merchant = merchant,
                index = index,
                maxCount = maxCount,
                showBar = showBars,
                color = visuals.primary,
            )
        }
    }
}

@Composable
private fun FrequentMerchantRow(
    merchant: FrequentMerchant,
    index: Int,
    maxCount: Int,
    showBar: Boolean,
    color: Color,
) {
    val track = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.faint)
    val progress = (merchant.count.toFloat() / maxCount.toFloat()).coerceIn(0f, 1f)
    val merchantFallback = stringResource(R.string.stats_lifestyle_merchant_fallback)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = (index + 1).toString(),
                modifier = Modifier.width(20.dp),
                style = MaterialTheme.typography.labelMedium.tabularNum(),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = merchant.merchant.ifBlank { merchantFallback },
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = stringResource(R.string.stats_frequent_merchants_count, merchant.count),
                style = MaterialTheme.typography.labelMedium.tabularNum(),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (showBar) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(5.dp)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(track),
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(progress)
                        .height(5.dp)
                        .clip(RoundedCornerShape(AppRadius.pill))
                        .background(color.copy(alpha = AppAlpha.opaque)),
                )
            }
        }
    }
}

@Composable
private fun ValueRegretSections(
    bestValueExpenses: List<Expense>,
    mostRegrettedExpenses: List<Expense>,
) {
    val visuals = LocalThemeVisuals.current
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Text(
            text = stringResource(R.string.stats_value_regret_title),
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (bestValueExpenses.isNotEmpty()) {
            ValueRegretSection(
                title = stringResource(R.string.stats_value_regret_value_section),
                expenses = bestValueExpenses,
                scoreText = { score -> stringResource(R.string.stats_value_regret_value_score, score) },
                scoreSelector = { it.valueScore },
            )
        }
        if (bestValueExpenses.isNotEmpty() && mostRegrettedExpenses.isNotEmpty()) {
            HorizontalDivider(color = visuals.chipUnselected.copy(alpha = AppAlpha.soft))
        }
        if (mostRegrettedExpenses.isNotEmpty()) {
            ValueRegretSection(
                title = stringResource(R.string.stats_value_regret_regret_section),
                expenses = mostRegrettedExpenses,
                scoreText = { score -> stringResource(R.string.stats_value_regret_regret_score, score) },
                scoreSelector = { it.regretScore },
            )
        }
    }
}

@Composable
private fun ValueRegretSection(
    title: String,
    expenses: List<Expense>,
    scoreText: @Composable (Int) -> String,
    scoreSelector: (Expense) -> Int?,
) {
    val visuals = LocalThemeVisuals.current
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(
            text = title,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        expenses.take(5).forEachIndexed { index, expense ->
            if (index > 0) {
                HorizontalDivider(color = visuals.chipUnselected.copy(alpha = AppAlpha.soft))
            }
            ValueRegretRow(
                expense = expense,
                scoreText = scoreSelector(expense)?.let { scoreText(it) },
            )
        }
    }
}

@Composable
private fun ValueRegretRow(
    expense: Expense,
    scoreText: String?,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val merchantFallback = stringResource(R.string.stats_lifestyle_merchant_fallback)
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = expense.merchant?.takeIf { it.isNotBlank() } ?: merchantFallback,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = expense.category,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Column(horizontalAlignment = Alignment.End) {
            Text(
                text = formatDisplayAmount(expense.amountCents, currencyDisplay),
                style = MaterialTheme.typography.labelLarge.tabularNum(),
                maxLines = 1,
            )
            scoreText?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
        }
    }
}

private fun hasLifestyleSignals(lifestyle: LifestyleStats): Boolean =
    lifestyle.aiSubscriptionAmountCents > 0L ||
        lifestyle.digitalAmountCents > 0L ||
        lifestyle.maxExpense != null
