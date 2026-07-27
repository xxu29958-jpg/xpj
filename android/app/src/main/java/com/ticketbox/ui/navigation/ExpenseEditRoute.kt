package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.SkeletonBlock
import com.ticketbox.ui.components.SkeletonScaffold
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ExpenseEditActionAvailability
import com.ticketbox.ui.screens.ExpenseEditBillSplitActions
import com.ticketbox.ui.screens.ExpenseEditItemizationActions
import com.ticketbox.ui.screens.ExpenseEditMediaActions
import com.ticketbox.ui.screens.ExpenseEditPrimaryActions
import com.ticketbox.ui.screens.ExpenseEditRelatedActions
import com.ticketbox.ui.screens.ExpenseEditScreen
import com.ticketbox.ui.screens.ExpenseEditScreenActions
import com.ticketbox.ui.screens.ExpenseEditScreenState
import com.ticketbox.ui.screens.ExpenseEditSplitEditingActions
import com.ticketbox.ui.screens.expense.ItemsEditorSheetActions
import com.ticketbox.ui.screens.expense.SplitsEditorSheetActions
import com.ticketbox.viewmodel.ExpenseEditUiState
import com.ticketbox.viewmodel.ExpenseEditViewModel
import com.ticketbox.viewmodel.acknowledgeItemsMismatch
import com.ticketbox.viewmodel.addItemRow
import com.ticketbox.viewmodel.cancelBillSplitInvitation
import com.ticketbox.viewmodel.closeBillSplitInviteSheet
import com.ticketbox.viewmodel.closeItemsEditor
import com.ticketbox.viewmodel.closeSplitsEditor
import com.ticketbox.viewmodel.evenSplitAmounts
import com.ticketbox.viewmodel.expenseEditViewModelFactory
import com.ticketbox.viewmodel.openBillSplitInviteSheet
import com.ticketbox.viewmodel.openItemsEditor
import com.ticketbox.viewmodel.openSplitsEditor
import com.ticketbox.viewmodel.removeItemRow
import com.ticketbox.viewmodel.saveItems
import com.ticketbox.viewmodel.saveSplits
import com.ticketbox.viewmodel.selectBillSplitInviteMember
import com.ticketbox.viewmodel.sendBillSplitInvite
import com.ticketbox.viewmodel.updateBillSplitInviteAmount
import com.ticketbox.viewmodel.updateItemDraft
import com.ticketbox.viewmodel.updateSplitAmount
import com.ticketbox.viewmodel.updateSplitIncluded

@Composable
internal fun ExpenseEditRoute(
    expenseId: Long,
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    onCompleted: (adviceInputsChanged: Boolean) -> Unit,
    onOpenRepaymentDrafts: (String) -> Unit,
) {
    val editViewModel: ExpenseEditViewModel = viewModel(
        key = "expense-edit-$expenseId",
        factory = expenseEditViewModelFactory(expenseId, screenFactory.repository),
    )
    val editState by editViewModel.uiState.collectAsStateWithLifecycle()
    val expense = editState.expense

    RepaymentDraftOpenEffect(editState, editViewModel, onOpenRepaymentDrafts)

    if (expense == null) {
        ExpenseEditLoadingRoute(
            state = editState,
            onBack = onBack,
            onRetry = editViewModel::retryLoadExpense,
        )
        return
    }

    ExpenseEditScreen(
        screenState = ExpenseEditScreenState(
            expense = expense,
            editState = editState,
            actionAvailability = ExpenseEditActionAvailability(
                allowConfirm = expense.status == "pending",
                allowReject = expense.status == "pending" || expense.status == "confirmed",
            ),
        ),
        actions = ExpenseEditScreenActions(
            primary = expenseEditPrimaryActions(editViewModel, onBack, onCompleted),
            media = expenseEditMediaActions(editViewModel),
            related = expenseEditRelatedActions(editViewModel),
            itemization = expenseEditItemizationActions(editViewModel),
            splitEditing = expenseEditSplitEditingActions(editViewModel),
            billSplit = expenseEditBillSplitActions(editViewModel),
        ),
    )
}

private fun expenseEditPrimaryActions(
    viewModel: ExpenseEditViewModel,
    onBack: () -> Unit,
    onCompleted: (adviceInputsChanged: Boolean) -> Unit,
): ExpenseEditPrimaryActions = ExpenseEditPrimaryActions(
    onSave = viewModel::save,
    onConfirm = viewModel::confirm,
    onReject = viewModel::reject,
    onDone = {
        if (viewModel.consumeDone()) {
            onCompleted(viewModel.consumeDoneAdviceInputsChanged())
        } else {
            onBack()
        }
    },
)

private fun expenseEditMediaActions(viewModel: ExpenseEditViewModel): ExpenseEditMediaActions = ExpenseEditMediaActions(
    onRetryOcr = viewModel::retryOcr,
    onRecognizeText = viewModel::recognizeText,
    onOpenRecognizeText = viewModel::openRecognizeTextDialog,
    onDismissRecognizeText = viewModel::closeRecognizeTextDialog,
    onLoadFullImage = viewModel::loadFullImage,
)

private fun expenseEditRelatedActions(viewModel: ExpenseEditViewModel): ExpenseEditRelatedActions =
    ExpenseEditRelatedActions(
        onKeepDuplicate = viewModel::markNotDuplicate,
        onCreateRepaymentDraft = viewModel::createRepaymentDraftFromExpense,
    )

private fun expenseEditItemizationActions(viewModel: ExpenseEditViewModel): ExpenseEditItemizationActions =
    ExpenseEditItemizationActions(
        onAcknowledgeItemsMismatch = viewModel::acknowledgeItemsMismatch,
        onEditItems = viewModel::openItemsEditor,
        editor = ItemsEditorSheetActions(
            onUpdate = viewModel::updateItemDraft,
            onAddRow = viewModel::addItemRow,
            onRemoveRow = viewModel::removeItemRow,
            onSave = viewModel::saveItems,
            onDismiss = viewModel::closeItemsEditor,
        ),
    )

private fun expenseEditSplitEditingActions(viewModel: ExpenseEditViewModel): ExpenseEditSplitEditingActions =
    ExpenseEditSplitEditingActions(
        onEditSplits = viewModel::openSplitsEditor,
        editor = SplitsEditorSheetActions(
            onToggleMember = viewModel::updateSplitIncluded,
            onUpdateAmount = viewModel::updateSplitAmount,
            onEvenSplit = viewModel::evenSplitAmounts,
            onSave = viewModel::saveSplits,
            onDismiss = viewModel::closeSplitsEditor,
        ),
    )

private fun expenseEditBillSplitActions(viewModel: ExpenseEditViewModel): ExpenseEditBillSplitActions =
    ExpenseEditBillSplitActions(
        onStartInvite = viewModel::openBillSplitInviteSheet,
        onCancelInvite = viewModel::cancelBillSplitInvitation,
        onSelectMember = viewModel::selectBillSplitInviteMember,
        onUpdateAmount = viewModel::updateBillSplitInviteAmount,
        onSend = viewModel::sendBillSplitInvite,
        onDismissSheet = viewModel::closeBillSplitInviteSheet,
    )

@Composable
private fun RepaymentDraftOpenEffect(
    state: ExpenseEditUiState,
    viewModel: ExpenseEditViewModel,
    onOpenRepaymentDrafts: (String) -> Unit,
) {
    LaunchedEffect(state.openRepaymentDraftPublicId) {
        val draftPublicId = viewModel.consumeOpenRepaymentDraftPublicId()
        if (draftPublicId != null) {
            onOpenRepaymentDrafts(draftPublicId)
        }
    }
}

@Composable
private fun ExpenseEditLoadingRoute(
    state: ExpenseEditUiState,
    onBack: () -> Unit,
    onRetry: () -> Unit,
) {
    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Edit,
            title = stringResource(R.string.expense_edit_loading_header_title),
            subtitle = stringResource(R.string.expense_edit_loading_header_subtitle),
            backText = stringResource(R.string.expense_edit_loading_back_button),
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ),
    ) {
        if (state.expenseLoading) {
            ExpenseEditLoadingInline(
                title = stringResource(R.string.expense_edit_loading_state_title),
                body = stringResource(R.string.expense_edit_loading_state_body),
            )
        } else {
            ExpenseEditLoadFailedInline(
                title = stringResource(R.string.expense_edit_loading_empty_title),
                body = state.message?.asString() ?: stringResource(R.string.expense_edit_loading_empty_fallback),
                onBack = onBack,
                onRetry = onRetry,
            )
        }
    }
}

@Composable
private fun ExpenseEditLoadingInline(
    title: String,
    body: String,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle))
        Text(text = title, style = MaterialTheme.typography.titleMedium)
        Text(
            text = body,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        SkeletonScaffold(
            isLoading = true,
            skeleton = {
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                    SkeletonBlock(modifier = Modifier.fillMaxWidth(0.74f).height(AppSpacing.compactGap))
                    SkeletonBlock(modifier = Modifier.fillMaxWidth(0.46f).height(AppSpacing.compactGap))
                }
            },
            content = {},
        )
    }
}

@Composable
private fun ExpenseEditLoadFailedInline(
    title: String,
    body: String,
    onBack: () -> Unit,
    onRetry: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle))
        Text(text = title, style = MaterialTheme.typography.titleMedium)
        Text(
            text = body,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        AppActionRow(
            primary = AppAction(
                text = stringResource(R.string.expense_edit_loading_reload_button),
                icon = Icons.Filled.Refresh,
                onClick = onRetry,
            ),
            secondary = AppAction(
                text = stringResource(R.string.expense_edit_loading_back_button),
                icon = Icons.AutoMirrored.Filled.ArrowBack,
                onClick = onBack,
            ),
            showDivider = false,
        )
    }
}
