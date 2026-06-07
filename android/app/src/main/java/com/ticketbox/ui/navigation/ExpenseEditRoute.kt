package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppEmptyStateCard
import com.ticketbox.ui.components.AppLoadingState
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ExpenseEditScreen
import com.ticketbox.viewmodel.ExpenseEditUiState
import com.ticketbox.viewmodel.ExpenseEditViewModel
import com.ticketbox.viewmodel.expenseEditViewModelFactory

@Composable
internal fun ExpenseEditRoute(
    expenseId: Long,
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    onCompleted: () -> Unit,
) {
    val editViewModel: ExpenseEditViewModel = viewModel(
        key = "expense-edit-$expenseId",
        factory = expenseEditViewModelFactory(expenseId, screenFactory.repository),
    )
    val editState by editViewModel.uiState.collectAsStateWithLifecycle()
    val expense = editState.expense

    if (expense == null) {
        ExpenseEditLoadingRoute(
            state = editState,
            onBack = onBack,
            onRetry = editViewModel::retryLoadExpense,
        )
        return
    }

    ExpenseEditScreen(
        expense = expense,
        state = editState,
        onSave = editViewModel::save,
        onConfirm = editViewModel::confirm,
        onReject = editViewModel::reject,
        onRetryOcr = editViewModel::retryOcr,
        onRecognizeText = editViewModel::recognizeText,
        onOpenRecognizeText = editViewModel::openRecognizeTextDialog,
        onDismissRecognizeText = editViewModel::closeRecognizeTextDialog,
        onLoadFullImage = editViewModel::loadFullImage,
        onKeepDuplicate = editViewModel::markNotDuplicate,
        onAcknowledgeItemsMismatch = editViewModel::acknowledgeItemsMismatch,
        onEditItems = editViewModel::openItemsEditor,
        onUpdateItemDraft = editViewModel::updateItemDraft,
        onAddItemRow = editViewModel::addItemRow,
        onRemoveItemRow = editViewModel::removeItemRow,
        onSaveItems = editViewModel::saveItems,
        onDismissItemsEditor = editViewModel::closeItemsEditor,
        onEditSplits = editViewModel::openSplitsEditor,
        onToggleSplitMember = editViewModel::updateSplitIncluded,
        onUpdateSplitAmount = editViewModel::updateSplitAmount,
        onEvenSplit = editViewModel::evenSplitAmounts,
        onSaveSplits = editViewModel::saveSplits,
        onDismissSplitsEditor = editViewModel::closeSplitsEditor,
        onDone = {
            if (editViewModel.consumeDone()) {
                onCompleted()
            } else {
                onBack()
            }
        },
        allowConfirm = expense.status == "pending",
        allowReject = expense.status == "pending",
    )
}

@Composable
private fun ExpenseEditLoadingRoute(
    state: ExpenseEditUiState,
    onBack: () -> Unit,
    onRetry: () -> Unit,
) {
    AppPageScrollableColumn(
        role = AppPageRole.Edit,
        hasBottomBar = false,
        includeStatusBarPadding = true,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        AppPageHeader(
            title = stringResource(R.string.expense_edit_loading_header_title),
            subtitle = stringResource(R.string.expense_edit_loading_header_subtitle),
            eyebrow = "",
        )

        if (state.expenseLoading) {
            AppLoadingState(
                title = stringResource(R.string.expense_edit_loading_state_title),
                body = stringResource(R.string.expense_edit_loading_state_body),
            )
        } else {
            AppEmptyStateCard {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
                ) {
                    Text(
                        text = stringResource(R.string.expense_edit_loading_empty_title),
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        text = state.message?.asString() ?: stringResource(R.string.expense_edit_loading_empty_fallback),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Button(
                        modifier = Modifier.fillMaxWidth(),
                        onClick = onRetry,
                    ) {
                        Text(stringResource(R.string.expense_edit_loading_reload_button))
                    }
                    AppOutlinedButton(
                        modifier = Modifier.fillMaxWidth(),
                        onClick = onBack,
                    ) {
                        Text(stringResource(R.string.expense_edit_loading_back_button))
                    }
                }
            }
        }
    }
}
