package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetCategoryBudget
import com.ticketbox.domain.model.BudgetExcludedCategory
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

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
            val (amountLabel, amountValue) = if (item.overspentAmountCents > 0L) {
                stringResource(R.string.budget_summary_metric_overspent) to
                    formatDisplayAmount(item.overspentAmountCents, currencyDisplay)
            } else {
                stringResource(R.string.budget_summary_metric_remaining) to
                    formatDisplayAmount(item.remainingAmountCents, currencyDisplay)
            }
            AmountRow(
                title = item.category,
                detail = stringResource(
                    R.string.budget_category_spent,
                    formatDisplayAmount(item.spentAmountCents, currencyDisplay),
                ),
                amountLabel = amountLabel,
                amountValue = amountValue,
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
                amountLabel = stringResource(R.string.budget_summary_metric_excluded),
                amountValue = formatDisplayAmount(item.amountCents, currencyDisplay),
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
    amountLabel: String,
    amountValue: String,
) {
    AppAdaptiveContentActionRow(
        modifier = Modifier.fillMaxWidth(),
        wideActionWeight = BUDGET_AMOUNT_ROW_TRAILING_WEIGHT,
        verticalAlignment = Alignment.Top,
        content = { AmountRowCopy(title = title, detail = detail) },
        action = { actionModifier ->
            BudgetTrailingAmount(
                label = amountLabel,
                amount = amountValue,
                modifier = actionModifier,
            )
        },
    )
}

@Composable
private fun AmountRowCopy(
    title: String,
    detail: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
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
}

private const val BUDGET_AMOUNT_ROW_TRAILING_WEIGHT = 0.44f

@Composable
private fun BudgetTrailingAmount(
    label: String,
    amount: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            textAlign = TextAlign.End,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        AppEndAlignedAmountText(
            modifier = Modifier.fillMaxWidth(),
            text = amount,
            role = AppAmountRole.Compact,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}
