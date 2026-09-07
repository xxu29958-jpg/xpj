package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.screens.BillSplitNavigation
import com.ticketbox.ui.screens.BillSplitScreen
import com.ticketbox.viewmodel.BillSplitViewModel
import com.ticketbox.viewmodel.billSplitViewModelFactory
import com.ticketbox.viewmodel.toUiText
import kotlinx.coroutines.launch

/** Relationships entry; the existing ledger switch and fact routes own result navigation. */
@Composable
internal fun BillSplitRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    onOpenExpense: (Long) -> Unit,
) {
    val viewModel: BillSplitViewModel = viewModel(
        factory = billSplitViewModelFactory(screenFactory.repository, screenFactory.ledgerRepository),
    )
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var opening by remember { mutableStateOf(false) }
    var openError by remember { mutableStateOf<UiText?>(null) }
    LaunchedEffect(state.access?.binding) { openError = null }
    BillSplitScreen(viewModel = viewModel, onBack = onBack,
        navigation = BillSplitNavigation(busy = opening, error = openError, openBill = { binding, expenseId, ledgerId ->
            if (!opening) {
                opening = true
                openError = null
                scope.launch {
                    try {
                        if (screenFactory.repository.captureDeferredLedgerBinding() != binding) return@launch
                        val switched = if (ledgerId == binding.ledgerId) Result.success(Unit)
                        else screenFactory.ledgerRepository.switchLedger(ledgerId, expectedBinding = binding).map { }
                        switched.onSuccess { onOpenExpense(expenseId) }.onFailure { error ->
                            if (screenFactory.repository.captureDeferredLedgerBinding() == binding) {
                                openError = error.toUiText(R.string.bill_split_open_failed)
                            }
                        }
                    } finally {
                        opening = false
                    }
                }
            }
        }),
    )
}
