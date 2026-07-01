package com.ticketbox.ui.screens.pending

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.runtime.Composable
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.screens.pending.sheets.BulkConfirmSheetContent
import com.ticketbox.ui.screens.pending.sheets.DuplicateConfirmSheetContent
import com.ticketbox.ui.screens.pending.sheets.MissingAmountSheetContent
import com.ticketbox.ui.screens.pending.sheets.QuickCategorySheetContent
import com.ticketbox.ui.screens.pending.sheets.QuickMerchantSheetContent
import com.ticketbox.ui.screens.pending.sheets.ReviewSheetChrome
import com.ticketbox.viewmodel.PendingSheet

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
    // Quick-fix sheets share the same review chrome and saving-state rule.
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
