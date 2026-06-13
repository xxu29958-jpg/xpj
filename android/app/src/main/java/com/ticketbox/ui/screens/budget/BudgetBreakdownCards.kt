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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetCategoryBudget
import com.ticketbox.domain.model.BudgetExcludedCategory
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun CategoryBudgetCard(
    items: List<BudgetCategoryBudget>,
    currencyDisplay: CurrencyDisplay,
) {
    BudgetListCard(
        title = stringResource(R.string.budget_category_card_title),
        emptyText = stringResource(R.string.budget_category_card_empty),
        hasItems = items.isNotEmpty(),
    ) {
        items.forEachIndexed { index, item ->
            if (index > 0) HorizontalDivider()
            AmountRow(
                title = item.category,
                detail = stringResource(
                    R.string.budget_category_spent,
                    formatDisplayAmount(item.spentAmountCents, currencyDisplay),
                ),
                amount = if (item.overspentAmountCents > 0L) {
                    stringResource(
                        R.string.budget_category_overspent,
                        formatDisplayAmount(item.overspentAmountCents, currencyDisplay),
                    )
                } else {
                    stringResource(
                        R.string.budget_category_remaining,
                        formatDisplayAmount(item.remainingAmountCents, currencyDisplay),
                    )
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
        title = stringResource(R.string.budget_excluded_card_title),
        emptyText = stringResource(R.string.budget_excluded_card_empty),
        hasItems = items.isNotEmpty(),
    ) {
        items.forEachIndexed { index, item ->
            if (index > 0) HorizontalDivider()
            AmountRow(
                title = item.category,
                detail = stringResource(R.string.budget_excluded_count, item.count),
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
            style = MaterialTheme.typography.titleSmall.tabularNum(),
            fontWeight = AppTextHierarchy.body.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
