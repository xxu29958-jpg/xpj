package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.FrequentMerchant
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun LifestyleCard(lifestyle: LifestyleStats) {
    val currencyDisplay = LocalCurrencyDisplay.current

    AppGlassCard(containerAlpha = 0.92f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            val merchantFallback = stringResource(R.string.stats_lifestyle_merchant_fallback)
            Text(stringResource(R.string.stats_lifestyle_title), style = MaterialTheme.typography.titleMedium)
            if (lifestyle.aiSubscriptionAmountCents > 0L) {
                LifestyleRow(
                    stringResource(R.string.stats_lifestyle_ai_subscription),
                    formatDisplayAmount(lifestyle.aiSubscriptionAmountCents, currencyDisplay),
                )
            }
            if (lifestyle.digitalAmountCents > 0L) {
                LifestyleRow(
                    stringResource(R.string.stats_lifestyle_digital),
                    formatDisplayAmount(lifestyle.digitalAmountCents, currencyDisplay),
                )
            }
            lifestyle.maxExpense?.let { maxExpense ->
                LifestyleRow(
                    label = stringResource(R.string.stats_lifestyle_max_expense),
                    value = stringResource(
                        R.string.stats_lifestyle_max_expense_value,
                        formatDisplayAmount(maxExpense.amountCents, currencyDisplay),
                        maxExpense.merchant?.takeIf { it.isNotBlank() } ?: merchantFallback,
                    ),
                )
            }
            if (
                lifestyle.aiSubscriptionAmountCents == 0L &&
                lifestyle.digitalAmountCents == 0L &&
                lifestyle.maxExpense == null
            ) {
                Text(
                    text = stringResource(R.string.stats_lifestyle_empty),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun LifestyleRow(
    label: String,
    value: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value)
    }
}

@Composable
internal fun FrequentMerchantsCard(merchants: List<FrequentMerchant>) {
    val visuals = LocalThemeVisuals.current
    AppGlassCard(containerAlpha = 0.92f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(stringResource(R.string.stats_frequent_merchants_title), style = MaterialTheme.typography.titleMedium)
            merchants.take(5).forEachIndexed { index, merchant ->
                if (index > 0) {
                    HorizontalDivider(color = visuals.chipUnselected.copy(alpha = 0.72f))
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        text = merchant.merchant,
                        style = MaterialTheme.typography.bodyLarge,
                    )
                    Text(
                        text = stringResource(R.string.stats_frequent_merchants_count, merchant.count),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}
