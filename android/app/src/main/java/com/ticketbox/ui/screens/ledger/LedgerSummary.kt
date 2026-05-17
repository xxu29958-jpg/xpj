package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.LedgerUiState

@Composable
internal fun LedgerSummaryStrip(state: LedgerUiState) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val total = state.items.sumOf { it.amountCents ?: 0L }
    AppGlassCard(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(
                horizontal = AppSpacing.cardPaddingSmall,
                vertical = AppSpacing.contentGap,
            ),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingSmall),
                verticalAlignment = Alignment.Bottom,
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
                ) {
                    Text(
                        text = "${displayMonthLabel(state.monthFilter)} 合计",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = formatDisplayAmount(total, currencyDisplay),
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = AppTextHierarchy.heading.weight,
                    )
                }
                Column(
                    modifier = Modifier.weight(1f),
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
                ) {
                    Text(
                        text = "账单",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelMedium,
                        textAlign = TextAlign.End,
                    )
                    Text(
                        text = "${state.items.size} 笔",
                        color = MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.titleMedium,
                        textAlign = TextAlign.End,
                    )
                }
            }
            LedgerSummaryTrendDots(state.items)
        }
    }
}

@Composable
private fun LedgerSummaryTrendDots(items: List<Expense>) {
    val visuals = LocalThemeVisuals.current
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap - 1.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val amounts = items.take(10).map { it.amountCents ?: 0L }
        val maxAmount = amounts.maxOrNull()?.takeIf { it > 0L } ?: 1L
        val sample = if (amounts.isEmpty()) {
            List(10) { 0L }
        } else {
            amounts + List((10 - amounts.size).coerceAtLeast(0)) { 0L }
        }
        sample.take(10).forEach { amount ->
            val width = if (amount > 0L) {
                (18 + 18 * (amount.toFloat() / maxAmount.toFloat()).coerceIn(0f, 1f)).dp
            } else {
                18.dp
            }
            Box(
                modifier = Modifier
                    .width(width)
                    .height(6.dp)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(
                        if (amount > 0L) {
                            visuals.primary.copy(alpha = 0.72f)
                        } else {
                            visuals.chipUnselected.copy(alpha = 0.70f)
                        },
                    ),
            )
        }
    }
}
