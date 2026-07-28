package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.duplicateNoticeBody
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun DuplicateConfirmSheetContent(
    expense: Expense,
    inProgress: Boolean,
    onKeepBoth: () -> Unit,
    onIgnoreCurrent: () -> Unit,
) {
    ReviewSheetScaffold(
        title = stringResource(R.string.pending_duplicate_sheet_title),
        subtitle = stringResource(R.string.pending_duplicate_sheet_hint),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = expense.merchant?.takeIf { it.isNotBlank() }
                    ?: stringResource(R.string.pending_duplicate_sheet_merchant_missing),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.body.weight,
            )
            Text(
                text = formatDisplayAmount(expense.amountCents, expense.recordCurrencyDisplay()),
                style = MaterialTheme.typography.bodyLarge.tabularNum(),
                fontWeight = AppTextHierarchy.body.weight,
            )
            expense.duplicateReason?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = stringResource(R.string.pending_duplicate_sheet_reason, duplicateNoticeBody(it)),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }

        AppSheetActionRow(
            primary = AppSheetAction(
                text = if (inProgress) {
                    stringResource(R.string.pending_duplicate_sheet_processing)
                } else {
                    stringResource(R.string.pending_duplicate_sheet_keep_both)
                },
                enabled = !inProgress,
                onClick = onKeepBoth,
            ),
            secondary = AppSheetAction(
                text = if (inProgress) stringResource(R.string.pending_duplicate_sheet_processing) else stringResource(R.string.pending_duplicate_sheet_ignore_current),
                enabled = !inProgress,
                onClick = onIgnoreCurrent,
            ),
        )
    }
}
