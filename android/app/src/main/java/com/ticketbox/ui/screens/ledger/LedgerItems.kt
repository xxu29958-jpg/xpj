package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatExpenseExchangeMeta
import com.ticketbox.ui.components.formatExpensePrimaryAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun LedgerDayHeader(label: String) {
    Text(
        text = label,
        color = MaterialTheme.colorScheme.onBackground,
        style = MaterialTheme.typography.titleSmall,
        fontWeight = AppTextHierarchy.heading.weight,
        modifier = Modifier.padding(top = AppSpacing.miniGap, bottom = AppSpacing.tinyGap),
    )
}

@Composable
internal fun LedgerExpenseCard(
    expense: Expense,
    onEdit: () -> Unit,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val visuals = LocalThemeVisuals.current
    val exchangeMeta = formatExpenseExchangeMeta(expense)
    AppGlassCard(
        modifier = Modifier.clickable(onClick = onEdit),
        containerAlpha = 0.995f,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.contentGap),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            LedgerCategoryMark(category = expense.category)
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = expense.merchant?.takeIf { it.isNotBlank() } ?: "未填写商家",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = AppTextHierarchy.body.weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                )
                expense.note?.takeIf { it.isNotBlank() }?.let {
                    Text(
                        text = it,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Column(
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = if (expense.amountCents == null) "待填写" else formatExpensePrimaryAmount(expense, currencyDisplay),
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                    maxLines = 1,
                )
                exchangeMeta?.let {
                    Text(
                        text = it,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelSmall,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Text(
                    text = expense.category,
                    modifier = Modifier
                        .clip(CircleShape)
                        .background(visuals.chipSelected.copy(alpha = 0.72f))
                        .padding(horizontal = AppSpacing.contentGap, vertical = AppSpacing.miniGap + AppSpacing.tinyGap),
                    color = visuals.primary,
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = AppTextHierarchy.caption.weight,
                    maxLines = 1,
                )
            }
        }
    }
}

@Composable
private fun LedgerCategoryMark(category: String) {
    val visuals = LocalThemeVisuals.current
    Box(
        modifier = Modifier
            .size(42.dp)
            .clip(RoundedCornerShape(AppRadius.small))
            .background(visuals.chipSelected.copy(alpha = 0.78f)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = category.take(1).ifBlank { "账" },
            color = visuals.primary,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
            textAlign = TextAlign.Center,
        )
    }
}
