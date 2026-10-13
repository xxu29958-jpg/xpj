package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.ticketbox.data.remote.dto.ExpenseConfirmationReceiptDto
import com.ticketbox.ui.screens.expense.ExpenseConfirmationScreen
import com.ticketbox.viewmodel.ExpenseEditUiState
import com.ticketbox.viewmodel.ExpenseEditViewModel

@Composable
internal fun ExpenseEditViewModel.ExpenseEditorCompletion(state: ExpenseEditUiState, factory: MainScreenFactory,
    exit: ExpenseEditExitActions, related: ExpenseFactNavigation, financialDataRevision: Int): Boolean {
    LaunchedEffect(state.done, state.confirmationReceipt) {
        if (state.done && state.confirmationReceipt == null && consumeDone()) {
            exit.onCompleted(consumeDoneAdviceInputsChanged())
        }
    }
    state.confirmationReceipt?.let { receipt ->
        ExpenseConfirmationRoute(receipt, factory, related, financialDataRevision) {
            consumeDone()
            exit.onCompleted(consumeDoneAdviceInputsChanged())
        }
    }
    return state.done || state.confirmationReceipt != null
}

/** The original result remains on its command; opening the bill reads the current fact owner. */
@Composable
internal fun ExpenseConfirmationRoute(
    receipt: ExpenseConfirmationReceiptDto,
    factory: MainScreenFactory,
    related: ExpenseFactNavigation,
    financialDataRevision: Int,
    onCompleted: () -> Unit,
) {
    var viewingFact by rememberSaveable(receipt.id, receipt.rowVersion) { mutableStateOf(false) }
    if (viewingFact) {
        ExpenseFactRoute(receipt.id, factory, { viewingFact = false }, related, financialDataRevision)
    } else {
        ExpenseConfirmationScreen(receipt, factory.ledgerRepository.currentLedgerName().orEmpty(),
            onOpenBill = { viewingFact = true }, onCompleted = onCompleted)
    }
}
