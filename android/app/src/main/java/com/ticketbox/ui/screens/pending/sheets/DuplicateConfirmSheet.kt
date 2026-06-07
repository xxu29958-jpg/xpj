package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay

/**
 * DuplicateConfirmSheet — slice 3 M6。
 *
 * 三选一：
 *  - 保留两笔（markNotDuplicate）
 *  - 忽略当前（rejectExpense）
 *  - 取消
 *
 * 严格不自动删除、不静默确认。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun DuplicateConfirmSheetContent(
    expense: Expense,
    inProgress: Boolean,
    onKeepBoth: () -> Unit,
    onIgnoreCurrent: () -> Unit,
    onDismiss: () -> Unit,
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            stringResource(R.string.pending_duplicate_sheet_title),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = stringResource(R.string.pending_duplicate_sheet_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )

        AppGlassCard(containerAlpha = 0.94f) {
            Column(
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = expense.merchant?.takeIf { it.isNotBlank() } ?: stringResource(R.string.pending_duplicate_sheet_merchant_missing),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTextHierarchy.body.weight,
                )
                Text(
                    text = formatDisplayAmount(expense.amountCents, currencyDisplay),
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = AppTextHierarchy.body.weight,
                )
                expense.duplicateReason?.takeIf { it.isNotBlank() }?.let {
                    Text(
                        text = stringResource(R.string.pending_duplicate_sheet_reason, it),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }

        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                modifier = Modifier.fillMaxWidth(),
                enabled = !inProgress,
                onClick = onKeepBoth,
            ) {
                Text(if (inProgress) stringResource(R.string.pending_duplicate_sheet_processing) else stringResource(R.string.pending_duplicate_sheet_keep_both))
            }
            AppSecondaryButton(
                text = if (inProgress) stringResource(R.string.pending_duplicate_sheet_processing) else stringResource(R.string.pending_duplicate_sheet_ignore_current),
                modifier = Modifier.fillMaxWidth(),
                enabled = !inProgress,
                onClick = onIgnoreCurrent,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                AppSecondaryButton(
                    text = stringResource(R.string.common_cancel),
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !inProgress,
                    onClick = onDismiss,
                )
            }
        }
    }
}
