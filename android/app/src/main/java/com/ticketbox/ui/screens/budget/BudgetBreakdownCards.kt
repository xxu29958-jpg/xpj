package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.BudgetCategoryBudget
import com.ticketbox.domain.model.BudgetExcludedCategory
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun CategoryBudgetCard(
    items: List<BudgetCategoryBudget>,
    currencyDisplay: CurrencyDisplay,
) {
    BudgetListCard(
        title = "分类执行",
        emptyText = "未设置分类预算。",
        hasItems = items.isNotEmpty(),
    ) {
        items.forEachIndexed { index, item ->
            if (index > 0) HorizontalDivider()
            AmountRow(
                title = item.category,
                detail = "已花 ${formatDisplayAmount(item.spentAmountCents, currencyDisplay)}",
                amount = if (item.overspentAmountCents > 0L) {
                    "超 ${formatDisplayAmount(item.overspentAmountCents, currencyDisplay)}"
                } else {
                    "剩 ${formatDisplayAmount(item.remainingAmountCents, currencyDisplay)}"
                },
            )
        }
    }
}

@Composable
internal fun ExcludedBreakdownCard(
    items: List<BudgetExcludedCategory>,
    currencyDisplay: CurrencyDisplay,
) {
    BudgetListCard(
        title = "剔除明细",
        emptyText = "本月没有被剔除的消费。",
        hasItems = items.isNotEmpty(),
    ) {
        items.forEachIndexed { index, item ->
            if (index > 0) HorizontalDivider()
            AmountRow(
                title = item.category,
                detail = "${item.count} 笔",
                amount = formatDisplayAmount(item.amountCents, currencyDisplay),
            )
        }
    }
}

@Composable
private fun BudgetListCard(
    title: String,
    emptyText: String,
    hasItems: Boolean,
    content: @Composable () -> Unit,
) {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            if (hasItems) {
                content()
            } else {
                Text(
                    text = emptyText,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

@Composable
private fun AmountRow(
    title: String,
    detail: String,
    amount: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(end = 12.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = detail,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text(
            text = amount,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.body.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
