package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.pending.sheets.BulkConfirmSheetContent
import com.ticketbox.ui.screens.pending.sheets.DuplicateConfirmSheetContent
import com.ticketbox.ui.screens.pending.sheets.MissingAmountSheetContent
import com.ticketbox.ui.screens.pending.sheets.QuickCategorySheetContent
import com.ticketbox.ui.screens.pending.sheets.QuickMerchantSheetContent
import com.ticketbox.ui.screens.pending.sheets.ReviewSheetChrome
import com.ticketbox.viewmodel.PendingSheet

/**
 * slice 3 M7 — Review BottomSheet 派发 + 批量确认入口卡片。
 *
 * 与 PendingScreen 分文件存放，保持 PendingScreen.kt ≤ 280 行。
 */
@Composable
@OptIn(ExperimentalMaterial3Api::class)
internal fun PendingReviewSheetHost(
    sheet: PendingSheet,
    categoryOptions: List<String>,
    actionInProgressIds: Set<Long>,
    readyCount: Int,
    missingAmountSkip: Int,
    duplicateSkip: Int,
    bulkRunning: Boolean,
    bulkConfirmed: Int,
    bulkTotal: Int,
    reviewRemaining: Int,
    statusMessage: String?,
    onSaveQuickCategory: (Long, String) -> Unit,
    onSaveQuickMerchant: (Long, String) -> Unit,
    onSaveAmountDraft: (Long, Long) -> Unit,
    onSaveAmountAndConfirm: (Long, Long) -> Unit,
    onSkipReviewField: () -> Unit,
    onKeepBoth: (Expense) -> Unit,
    onIgnoreCurrent: (Expense) -> Unit,
    onConfirmReady: () -> Unit,
    onDismiss: () -> Unit,
) {
    // 三个快补 sheet 共享的连续审阅外壳（计数/状态/跳过 + 保存中标记）。各 sheet 的
    // saving 取「当前票是否在 actionInProgressIds 里」，其余三项全 sheet 同值。
    fun chromeFor(expenseId: Long) = ReviewSheetChrome(
        saving = expenseId in actionInProgressIds,
        remaining = reviewRemaining,
        statusMessage = statusMessage,
        onSkip = onSkipReviewField,
    )
    when (sheet) {
        is PendingSheet.None -> Unit
        is PendingSheet.QuickCategory -> ModalBottomSheet(onDismissRequest = onDismiss) {
            QuickCategorySheetContent(
                expense = sheet.expense,
                options = categoryOptions,
                chrome = chromeFor(sheet.expense.id),
                onSave = { value -> onSaveQuickCategory(sheet.expense.id, value) },
                onDismiss = onDismiss,
            )
        }
        is PendingSheet.QuickMerchant -> ModalBottomSheet(onDismissRequest = onDismiss) {
            QuickMerchantSheetContent(
                expense = sheet.expense,
                chrome = chromeFor(sheet.expense.id),
                onSave = { value -> onSaveQuickMerchant(sheet.expense.id, value) },
                onDismiss = onDismiss,
            )
        }
        is PendingSheet.MissingAmount -> ModalBottomSheet(onDismissRequest = onDismiss) {
            MissingAmountSheetContent(
                expense = sheet.expense,
                chrome = chromeFor(sheet.expense.id),
                onSaveDraft = { cents -> onSaveAmountDraft(sheet.expense.id, cents) },
                onSaveAndConfirm = { cents -> onSaveAmountAndConfirm(sheet.expense.id, cents) },
                onDismiss = onDismiss,
            )
        }
        is PendingSheet.Duplicate -> ModalBottomSheet(onDismissRequest = onDismiss) {
            DuplicateConfirmSheetContent(
                expense = sheet.expense,
                inProgress = sheet.expense.id in actionInProgressIds,
                onKeepBoth = { onKeepBoth(sheet.expense) },
                onIgnoreCurrent = { onIgnoreCurrent(sheet.expense) },
                onDismiss = onDismiss,
            )
        }
        is PendingSheet.BulkConfirm -> ModalBottomSheet(onDismissRequest = onDismiss) {
            BulkConfirmSheetContent(
                readyCount = readyCount,
                missingAmountSkipCount = missingAmountSkip,
                duplicateSkipCount = duplicateSkip,
                inProgress = bulkRunning,
                confirmedCount = bulkConfirmed,
                totalCount = bulkTotal,
                onConfirmReady = onConfirmReady,
                onDismiss = onDismiss,
            )
        }
    }
}

@Composable
internal fun BulkConfirmEntry(
    readyCount: Int,
    inProgress: Boolean,
    onOpen: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = AppSpacing.tinyGap),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = stringResource(R.string.pending_bulk_entry_ready, readyCount),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            AppSecondaryButton(
                text = if (inProgress) {
                    stringResource(R.string.pending_bulk_entry_in_progress)
                } else {
                    stringResource(R.string.pending_bulk_entry_button)
                },
                enabled = !inProgress,
                onClick = onOpen,
            )
        }
    }
}
