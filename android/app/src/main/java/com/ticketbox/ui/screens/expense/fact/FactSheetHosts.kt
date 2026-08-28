package com.ticketbox.ui.screens.expense.fact

import androidx.compose.runtime.Composable
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.screens.expense.BillSplitInviteSheet
import com.ticketbox.ui.screens.expense.BillSplitInviteSheetActions
import com.ticketbox.ui.screens.expense.BillSplitInviteSheetState
import com.ticketbox.ui.screens.expense.ItemsEditorSheet
import com.ticketbox.ui.screens.expense.ItemsEditorSheetActions
import com.ticketbox.ui.screens.expense.ItemsEditorSheetState
import com.ticketbox.ui.screens.expense.SplitsEditorSheet
import com.ticketbox.ui.screens.expense.SplitsEditorSheetActions
import com.ticketbox.ui.screens.expense.SplitsEditorSheetState
import com.ticketbox.ui.screens.expense.correction.ExpenseCorrectionSheet
import com.ticketbox.ui.screens.expense.correction.ExpenseCorrectionSheetActions
import com.ticketbox.viewmodel.BillSplitSentLoadState
import com.ticketbox.viewmodel.CorrectionScalarField
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.ExpenseFactViewModel
import com.ticketbox.viewmodel.adoptCorrectionItems
import com.ticketbox.viewmodel.adoptCorrectionSplits
import com.ticketbox.viewmodel.addCorrectionItemRow
import com.ticketbox.viewmodel.canSubmitCorrection
import com.ticketbox.viewmodel.cancelBillSplitInvitation
import com.ticketbox.viewmodel.closeBillSplitInviteSheet
import com.ticketbox.viewmodel.closeCorrectionSheet
import com.ticketbox.viewmodel.dismissCorrectionItemsEditor
import com.ticketbox.viewmodel.dismissCorrectionSplitsEditor
import com.ticketbox.viewmodel.evenCorrectionSplitAmounts
import com.ticketbox.viewmodel.factActiveSplitCentsFor
import com.ticketbox.viewmodel.openCorrectionItemsEditor
import com.ticketbox.viewmodel.openCorrectionSplitsEditor
import com.ticketbox.viewmodel.removeCorrectionItemRow
import com.ticketbox.viewmodel.selectBillSplitInviteMember
import com.ticketbox.viewmodel.sendBillSplitInvite
import com.ticketbox.viewmodel.submitCorrection
import com.ticketbox.viewmodel.updateBillSplitInviteAmount
import com.ticketbox.viewmodel.updateCorrectionField
import com.ticketbox.viewmodel.updateCorrectionScore
import com.ticketbox.viewmodel.updateCorrectionCurrency
import com.ticketbox.viewmodel.updateCorrectionItemDraft
import com.ticketbox.viewmodel.updateCorrectionSplitDraft

/**
 * A1 事实屏的 sheet 托管（detekt 拆分：ExpenseFactScreen 只留正文编排）。
 * 更正 sheet / 明细子 surface / 拆账子 surface / 拆账邀请 sheet。
 */
@Composable
internal fun ExpenseFactSheetHosts(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
    FactBillSplitInviteHost(state = state, viewModel = viewModel)
    FactCorrectionHost(state = state, viewModel = viewModel)
    FactCorrectionLinesHosts(state = state, viewModel = viewModel)
}

@Composable
private fun FactBillSplitInviteHost(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
    val expense = state.expense ?: return
    if (!state.billSplitInviteSheetOpen) return
    val remainingCents = expense.amountCents?.let { parent ->
        parent - state.billSplitSent.factActiveSplitCentsFor(expense.id)
    }
    BillSplitInviteSheet(
        state = BillSplitInviteSheetState(
            members = state.billSplitInviteMembers,
            membersLoading = state.billSplitInviteMembersLoading,
            selectedMemberId = state.billSplitInviteSelectedMemberId,
            amountText = state.billSplitInviteAmountText,
            sending = state.billSplitInviteSending,
            message = state.billSplitInviteMessage,
            messageTone = state.billSplitInviteMessageTone,
            display = expense.recordCurrencyDisplay(),
        ),
        remainingCents = remainingCents,
        remainingUnavailable = state.billSplitSentLoadState != BillSplitSentLoadState.Loaded,
        actions = BillSplitInviteSheetActions(
            onSelectMember = viewModel::selectBillSplitInviteMember,
            onUpdateAmount = viewModel::updateBillSplitInviteAmount,
            onSend = viewModel::sendBillSplitInvite,
            onDismiss = viewModel::closeBillSplitInviteSheet,
        ),
    )
}

@Composable
private fun FactCorrectionHost(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
    if (!state.correction.open) return
    ExpenseCorrectionSheet(
        state = state,
        canSubmit = viewModel.canSubmitCorrection(),
        actions = ExpenseCorrectionSheetActions(
            onReasonChange = { viewModel.updateCorrectionField(CorrectionScalarField.Reason, it) },
            onMerchantChange = { viewModel.updateCorrectionField(CorrectionScalarField.Merchant, it) },
            onCategoryChange = { viewModel.updateCorrectionField(CorrectionScalarField.Category, it) },
            onTagsChange = { viewModel.updateCorrectionField(CorrectionScalarField.Tags, it) },
            onNoteChange = { viewModel.updateCorrectionField(CorrectionScalarField.Note, it) },
            onAmountChange = { viewModel.updateCorrectionField(CorrectionScalarField.Amount, it) },
            onExpenseTimeChange = { viewModel.updateCorrectionField(CorrectionScalarField.ExpenseTime, it) },
            onCurrencyChange = viewModel::updateCorrectionCurrency,
            onScoreChange = viewModel::updateCorrectionScore,
            onOpenItems = viewModel::openCorrectionItemsEditor,
            onOpenSplits = viewModel::openCorrectionSplitsEditor,
            onSubmit = viewModel::submitCorrection,
            onDismiss = viewModel::closeCorrectionSheet,
        ),
    )
}

@Composable
private fun FactCorrectionLinesHosts(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
    val expense = state.expense ?: return
    if (state.correction.itemsEditorOpen) {
        ItemsEditorSheet(
            state = ItemsEditorSheetState(
                drafts = state.correction.itemDrafts,
                parentAmountCents = expense.amountCents,
                saving = false,
                display = expense.recordCurrencyDisplay(),
            ),
            actions = ItemsEditorSheetActions(
                onUpdate = viewModel::updateCorrectionItemDraft,
                onAddRow = viewModel::addCorrectionItemRow,
                onRemoveRow = viewModel::removeCorrectionItemRow,
                onSave = viewModel::adoptCorrectionItems,
                onDismiss = viewModel::dismissCorrectionItemsEditor,
            ),
        )
    }
    if (state.correction.splitEditorOpen) {
        SplitsEditorSheet(
            state = SplitsEditorSheetState(
                drafts = state.correction.splitDrafts,
                parentAmountCents = expense.amountCents,
                saving = false,
                loading = state.correction.splitMembersLoading,
                display = expense.recordCurrencyDisplay(),
            ),
            actions = SplitsEditorSheetActions(
                onToggleMember = { memberId, included ->
                    viewModel.updateCorrectionSplitDraft(memberId, included = included)
                },
                onUpdateAmount = { memberId, amount ->
                    viewModel.updateCorrectionSplitDraft(memberId, amountText = amount)
                },
                onEvenSplit = viewModel::evenCorrectionSplitAmounts,
                onSave = viewModel::adoptCorrectionSplits,
                onDismiss = viewModel::dismissCorrectionSplitsEditor,
            ),
        )
    }
}
