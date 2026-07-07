package com.ticketbox.ui.screens.pending

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.runtime.Composable
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.screens.pending.sheets.BulkConfirmSheetActions
import com.ticketbox.ui.screens.pending.sheets.BulkConfirmSheetContent
import com.ticketbox.ui.screens.pending.sheets.BulkConfirmSheetState
import com.ticketbox.ui.screens.pending.sheets.DuplicateConfirmSheetContent
import com.ticketbox.ui.screens.pending.sheets.MissingAmountSheetContent
import com.ticketbox.ui.screens.pending.sheets.QuickCategorySheetContent
import com.ticketbox.ui.screens.pending.sheets.QuickMerchantSheetContent
import com.ticketbox.ui.screens.pending.sheets.ReviewSheetChrome
import com.ticketbox.viewmodel.PendingSheet

internal data class PendingReviewSheetHostState(
    val sheet: PendingSheet,
    val categoryOptions: List<String>,
    val actionInProgressIds: Set<Long>,
    val readyCount: Int,
    val missingAmountSkip: Int,
    val duplicateSkip: Int,
    val bulkRunning: Boolean,
    val bulkConfirmed: Int,
    val bulkTotal: Int,
    val reviewRemaining: Int,
    val statusMessage: String?,
)

data class PendingReviewSheetHostActions(
    val onSaveQuickCategory: (Long, String) -> Unit,
    val onSaveQuickMerchant: (Long, String) -> Unit,
    val onSaveAmountDraft: (Long, Long) -> Unit,
    val onSaveAmountAndConfirm: (Long, Long) -> Unit,
    val onSkipReviewField: () -> Unit,
    val onKeepBoth: (Expense) -> Unit,
    val onIgnoreCurrent: (Expense) -> Unit,
    val onConfirmReady: () -> Unit,
    val onDismiss: () -> Unit,
)

@Composable
@OptIn(ExperimentalMaterial3Api::class)
internal fun PendingReviewSheetHost(
    state: PendingReviewSheetHostState,
    actions: PendingReviewSheetHostActions,
) {
    // Quick-fix sheets share the same review chrome and saving-state rule.
    fun chromeFor(expenseId: Long) = ReviewSheetChrome(
        saving = expenseId in state.actionInProgressIds,
        remaining = state.reviewRemaining,
        statusMessage = state.statusMessage,
        onSkip = actions.onSkipReviewField,
    )
    when (val sheet = state.sheet) {
        is PendingSheet.None -> Unit
        is PendingSheet.QuickCategory -> ModalBottomSheet(onDismissRequest = actions.onDismiss) {
            QuickCategorySheetContent(
                expense = sheet.expense,
                options = state.categoryOptions,
                chrome = chromeFor(sheet.expense.id),
                onSave = { value -> actions.onSaveQuickCategory(sheet.expense.id, value) },
                onDismiss = actions.onDismiss,
            )
        }
        is PendingSheet.QuickMerchant -> ModalBottomSheet(onDismissRequest = actions.onDismiss) {
            QuickMerchantSheetContent(
                expense = sheet.expense,
                chrome = chromeFor(sheet.expense.id),
                onSave = { value -> actions.onSaveQuickMerchant(sheet.expense.id, value) },
                onDismiss = actions.onDismiss,
            )
        }
        is PendingSheet.MissingAmount -> ModalBottomSheet(onDismissRequest = actions.onDismiss) {
            MissingAmountSheetContent(
                expense = sheet.expense,
                chrome = chromeFor(sheet.expense.id),
                onSaveDraft = { cents -> actions.onSaveAmountDraft(sheet.expense.id, cents) },
                onSaveAndConfirm = { cents -> actions.onSaveAmountAndConfirm(sheet.expense.id, cents) },
            )
        }
        is PendingSheet.Duplicate -> ModalBottomSheet(onDismissRequest = actions.onDismiss) {
            DuplicateConfirmSheetContent(
                expense = sheet.expense,
                inProgress = sheet.expense.id in state.actionInProgressIds,
                onKeepBoth = { actions.onKeepBoth(sheet.expense) },
                onIgnoreCurrent = { actions.onIgnoreCurrent(sheet.expense) },
            )
        }
        is PendingSheet.BulkConfirm -> ModalBottomSheet(onDismissRequest = actions.onDismiss) {
            BulkConfirmSheetContent(
                state = BulkConfirmSheetState(
                    readyCount = state.readyCount,
                    missingAmountSkipCount = state.missingAmountSkip,
                    duplicateSkipCount = state.duplicateSkip,
                    inProgress = state.bulkRunning,
                    confirmedCount = state.bulkConfirmed,
                    totalCount = state.bulkTotal,
                ),
                actions = BulkConfirmSheetActions(
                    onConfirmReady = actions.onConfirmReady,
                    onDismiss = actions.onDismiss,
                ),
            )
        }
    }
}
