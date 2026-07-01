package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetCategoryBudget
import com.ticketbox.domain.model.BudgetExcludedCategory
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun CategoryBudgetSection(
    items: List<BudgetCategoryBudget>,
    currencyDisplay: CurrencyDisplay,
) {
    BudgetListSection(
        title = stringResource(R.string.budget_category_card_title),
        emptyText = stringResource(R.string.budget_category_card_empty),
        hasItems = items.isNotEmpty(),
    ) {
        items.forEachIndexed { index, item ->
            if (index > 0) BudgetRowDivider()
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
internal fun ExcludedBreakdownSection(
    items: List<BudgetExcludedCategory>,
    currencyDisplay: CurrencyDisplay,
) {
    BudgetListSection(
        title = stringResource(R.string.budget_excluded_card_title),
        emptyText = stringResource(R.string.budget_excluded_card_empty),
        hasItems = items.isNotEmpty(),
    ) {
        items.forEachIndexed { index, item ->
            if (index > 0) BudgetRowDivider()
            AmountRow(
                title = item.category,
                detail = stringResource(R.string.budget_excluded_count, item.count),
                amount = formatDisplayAmount(item.amountCents, currencyDisplay),
            )
        }
    }
}

@Composable
private fun BudgetListSection(
    title: String,
    emptyText: String,
    hasItems: Boolean,
    content: @Composable () -> Unit,
) {
    BudgetOpenSection(
        title = title,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
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
                .padding(end = AppSpacing.compactGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = AppTextHierarchy.body.weight,
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
            maxLines = 2,
        )
    }
}
