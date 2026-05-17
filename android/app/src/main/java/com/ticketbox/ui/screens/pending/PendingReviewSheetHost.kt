package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.screens.pending.sheets.BulkConfirmSheetContent
import com.ticketbox.ui.screens.pending.sheets.DuplicateConfirmSheetContent
import com.ticketbox.ui.screens.pending.sheets.MissingAmountSheetContent
import com.ticketbox.ui.screens.pending.sheets.QuickCategorySheetContent
import com.ticketbox.ui.screens.pending.sheets.QuickMerchantSheetContent
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
    onSaveQuickCategory: (Long, String) -> Unit,
    onSaveQuickMerchant: (Long, String) -> Unit,
    onSaveAmountDraft: (Long, Long) -> Unit,
    onSaveAmountAndConfirm: (Long, Long) -> Unit,
    onKeepBoth: (Expense) -> Unit,
    onIgnoreCurrent: (Expense) -> Unit,
    onConfirmReady: () -> Unit,
    onDismiss: () -> Unit,
) {
    when (sheet) {
        is PendingSheet.None -> Unit
        is PendingSheet.QuickCategory -> ModalBottomSheet(onDismissRequest = onDismiss) {
            QuickCategorySheetContent(
                expense = sheet.expense,
                options = categoryOptions,
                saving = sheet.expense.id in actionInProgressIds,
                onSave = { value -> onSaveQuickCategory(sheet.expense.id, value) },
                onDismiss = onDismiss,
            )
        }
        is PendingSheet.QuickMerchant -> ModalBottomSheet(onDismissRequest = onDismiss) {
            QuickMerchantSheetContent(
                expense = sheet.expense,
                saving = sheet.expense.id in actionInProgressIds,
                onSave = { value -> onSaveQuickMerchant(sheet.expense.id, value) },
                onDismiss = onDismiss,
            )
        }
        is PendingSheet.MissingAmount -> ModalBottomSheet(onDismissRequest = onDismiss) {
            MissingAmountSheetContent(
                expense = sheet.expense,
                saving = sheet.expense.id in actionInProgressIds,
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
    AppGlassCard(containerAlpha = 0.94f) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "可直接确认 $readyCount 条",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            AppSecondaryButton(
                text = if (inProgress) "确认中…" else "批量确认",
                enabled = !inProgress,
                onClick = onOpen,
            )
        }
    }
}
