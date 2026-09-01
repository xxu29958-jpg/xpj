package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun LedgerListTextBlock(
    expense: Expense,
    metaText: String,
    modifier: Modifier,
    lineageStatus: ExpenseLineageStatus = ExpenseLineageStatus.Confirmed,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = expense.merchant?.takeIf { it.isNotBlank() } ?: stringResource(R.string.ledger_item_merchant_empty),
                modifier = Modifier.weight(1f, fill = false),
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = AppTextHierarchy.body.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            LedgerLineageChip(status = lineageStatus)
        }
        Text(
            text = metaText,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
