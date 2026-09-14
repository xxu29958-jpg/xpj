package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.ui.asString
import com.ticketbox.ui.screens.ManualExpenseSheet
import com.ticketbox.ui.screens.ManualExpenseSheetActions
import com.ticketbox.ui.screens.ManualExpenseSheetInitials
import com.ticketbox.ui.screens.ManualExpenseSheetState
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel

@Composable
internal fun recurringOccurrenceModel(factory: MainScreenFactory, onChanged: () -> Unit): RecurringOccurrenceViewModel =
    viewModel(factory = viewModelFactory {
        initializer {
            RecurringOccurrenceViewModel(
                factory.recurringRepository.occurrences,
                factory.repository,
                factory.debtRepository,
                onChanged,
                createSavedStateHandle(),
            )
        }
    })

@Composable
internal fun RecurringOccurrenceHost(
    model: RecurringOccurrenceViewModel,
    onOpenExpense: (Long) -> Unit,
    onOpenManualSubmission: (String) -> Unit = {},
) {
    val state by model.uiState.collectAsStateWithLifecycle()
    RecurringOccurrenceSheet(state, OccurrenceSheetActions(
        onDismiss = model::dismiss,
        onRefresh = model::refresh,
        onPeriod = model::changePeriod,
        onChoose = model::choose,
        onSubmit = model::submit,
        onRecover = model::recover,
        onOpenExpense = { id -> model.dismiss(); onOpenExpense(id) },
        onRecordPayment = model.periodPayment::recordPeriodPayment,
    ))
    val origin = state.periodPaymentOrigin
    val paymentCurrency = CurrencyCode.fromStorageKeyOrNull(origin?.obligationCurrencyCode)
    val ledgerHomeCurrency = CurrencyCode.fromStorageKeyOrNull(origin?.ledgerHomeCurrencyCode)
    if (origin != null && origin.binding == state.access?.binding && paymentCurrency != null && ledgerHomeCurrency != null) {
        ManualExpenseSheet(
            state = ManualExpenseSheetState(
                categories = emptyList(),
                saving = state.periodPaymentSaving,
                initialCurrency = paymentCurrency,
                ledgerHomeCurrency = ledgerHomeCurrency,
                errorMessage = state.periodPaymentError?.asString(),
            ),
            actions = ManualExpenseSheetActions(
                onCreate = { draft ->
                    if (state.access?.binding != origin.binding || state.periodPaymentSaving) return@ManualExpenseSheetActions
                    model.createPeriodPayment(draft, onAdmitted = onOpenManualSubmission)
                },
                onDismiss = model.periodPayment::dismissPeriodPayment,
            ),
            initials = ManualExpenseSheetInitials(
                merchant = origin.merchant,
                category = origin.category?.takeIf { it.isNotBlank() } ?: DEFAULT_EXPENSE_CATEGORIES.first(),
                note = origin.note.orEmpty(),
                amountMinor = origin.capturedAmountCents ?: origin.plannedAmountCents,
            ),
        )
    }
}
