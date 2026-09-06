package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel

@Composable
internal fun recurringOccurrenceModel(factory: MainScreenFactory, onChanged: () -> Unit): RecurringOccurrenceViewModel =
    viewModel(factory = viewModelFactory {
        initializer {
            RecurringOccurrenceViewModel(factory.recurringRepository.occurrences, factory.repository, factory.outboxRepository, onChanged)
        }
    })

@Composable
internal fun RecurringOccurrenceHost(model: RecurringOccurrenceViewModel, onOpenExpense: (Long) -> Unit) {
    val state by model.uiState.collectAsStateWithLifecycle()
    val currency = LocalCurrencyDisplay.current
    RecurringOccurrenceSheet(state, currency, OccurrenceSheetActions(
        onDismiss = model::dismiss,
        onRefresh = model::refresh,
        onPeriod = model::changePeriod,
        onChoose = { model.choose(it, currency.homeCurrency) },
        onSubmit = model::submit,
        onRecover = model::recover,
        onOpenExpense = { id -> model.dismiss(); onOpenExpense(id) },
    ))
}
