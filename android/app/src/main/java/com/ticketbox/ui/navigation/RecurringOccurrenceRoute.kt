package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.screens.ManualExpenseSheet
import com.ticketbox.ui.screens.ManualExpenseSheetActions
import com.ticketbox.ui.screens.ManualExpenseSheetState
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import kotlinx.coroutines.launch

@Composable
internal fun recurringOccurrenceModel(factory: MainScreenFactory, onChanged: () -> Unit): RecurringOccurrenceViewModel =
    viewModel(factory = viewModelFactory {
        initializer {
            RecurringOccurrenceViewModel(factory.recurringRepository.occurrences, factory.repository, onChanged)
        }
    })

@Composable
internal fun RecurringOccurrenceHost(
    model: RecurringOccurrenceViewModel,
    ledger: LedgerActions,
    onOpenExpense: (Long) -> Unit,
    onOpenManualSubmission: (String) -> Unit = {},
) {
    val state by model.uiState.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    RecurringOccurrenceSheet(state, OccurrenceSheetActions(
        onDismiss = model::dismiss,
        onRefresh = model::refresh,
        onPeriod = model::changePeriod,
        onChoose = model::choose,
        onSubmit = model::submit,
        onRecover = model::recover,
        onOpenExpense = { id -> model.dismiss(); onOpenExpense(id) },
        onRecordPayment = model::recordPeriodPayment,
    ))
    val origin = state.periodPaymentOrigin
    val paymentCurrency = CurrencyCode.fromStorageKeyOrNull(origin?.obligationCurrencyCode)
    val ledgerHomeCurrency = CurrencyCode.fromStorageKeyOrNull(origin?.ledgerHomeCurrencyCode)
    if (origin != null && origin.binding == state.access?.binding && paymentCurrency != null && ledgerHomeCurrency != null) {
        ManualExpenseSheet(
            state = ManualExpenseSheetState(
                categories = emptyList(),
                saving = false,
                initialCurrency = paymentCurrency,
                ledgerHomeCurrency = ledgerHomeCurrency,
            ),
            actions = ManualExpenseSheetActions(
                onCreate = { draft ->
                    if (state.access?.binding != origin.binding) return@ManualExpenseSheetActions
                    scope.launch {
                        model.capturePeriodPaymentDraft(
                            category = draft.category.orEmpty(),
                            note = draft.note.orEmpty(),
                            currencyCode = draft.originalCurrencyCode?.storageKey ?: paymentCurrency.storageKey,
                            amountCents = draft.originalAmountMinor ?: draft.amountCents ?: 0L,
                        )
                        val result = ledger.createManualExpense(
                            draft.copy(
                                clientRef = origin.clientRef,
                                ledgerHomeCurrency = draft.ledgerHomeCurrency ?: ledgerHomeCurrency,
                            ),
                        )
                        if (result.isSuccess) {
                            model.dismissPeriodPayment()
                            onOpenManualSubmission(origin.clientRef)
                        }
                    }
                },
                onDismiss = model::dismissPeriodPayment,
            ),
        )
    }
}
