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
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppTextHierarchy

/**
 * BulkConfirm BottomSheet — slice 3 M5。
 *
 * 调用方负责传入「可直接确认」筛选下的统计：
 *  - readyCount：amount 完整、非 suspected 的可确认数量
 *  - missingAmountSkipCount：缺金额会被跳过的数量
 *  - duplicateSkipCount：疑似重复会被跳过、需单独二次确认的数量
 *
 * 操作：
 *  - 二次确认 → onConfirmReady() 触发 ViewModel.confirmReadyExpenses
 *  - 缺金额跳过，疑似重复跳过；任何失败不影响其他项
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun BulkConfirmSheetContent(
    readyCount: Int,
    missingAmountSkipCount: Int,
    duplicateSkipCount: Int,
    inProgress: Boolean,
    confirmedCount: Int,
    totalCount: Int,
    onConfirmReady: () -> Unit,
    onDismiss: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            stringResource(R.string.pending_bulk_sheet_title),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = stringResource(R.string.pending_bulk_sheet_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )

        AppGlassCard(containerAlpha = 0.94f) {
            Column(
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                StatLine(
                    label = stringResource(R.string.pending_bulk_sheet_stat_will_confirm),
                    value = stringResource(R.string.pending_bulk_sheet_stat_count, readyCount),
                )
                if (missingAmountSkipCount > 0) {
                    StatLine(
                        label = stringResource(R.string.pending_bulk_sheet_stat_skip_missing_amount),
                        value = stringResource(R.string.pending_bulk_sheet_stat_count, missingAmountSkipCount),
                    )
                }
                if (duplicateSkipCount > 0) {
                    StatLine(
                        label = stringResource(R.string.pending_bulk_sheet_stat_skip_duplicate),
                        value = stringResource(R.string.pending_bulk_sheet_stat_skip_duplicate_count, duplicateSkipCount),
                    )
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppSecondaryButton(
                text = stringResource(R.string.common_cancel),
                modifier = Modifier.weight(1f),
                enabled = !inProgress,
                onClick = onDismiss,
            )
            Button(
                modifier = Modifier.weight(1.4f),
                enabled = !inProgress && readyCount > 0,
                onClick = onConfirmReady,
            ) {
                Text(confirmButtonLabel(inProgress, confirmedCount, totalCount, readyCount))
            }
        }
    }
}

/** Confirm-button label: live "已确认 N/M" progress over the run total, else the count CTA. */
@Composable
private fun confirmButtonLabel(
    inProgress: Boolean,
    confirmedCount: Int,
    totalCount: Int,
    readyCount: Int,
): String = when {
    inProgress && totalCount > 0 -> stringResource(R.string.pending_bulk_sheet_progress, confirmedCount, totalCount)
    inProgress -> stringResource(R.string.pending_bulk_sheet_in_progress)
    else -> stringResource(R.string.pending_bulk_sheet_confirm_button, readyCount)
}

@Composable
private fun StatLine(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
        Text(value, fontWeight = AppTextHierarchy.body.weight, style = MaterialTheme.typography.bodyMedium)
    }
}
