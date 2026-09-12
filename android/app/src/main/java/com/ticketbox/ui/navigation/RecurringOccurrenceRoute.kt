package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.compose.currentStateAsState
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.data.repository.ExpenseRepository
import kotlinx.coroutines.flow.flowOf
import java.util.UUID

@Composable
internal fun recurringOccurrenceModel(factory: MainScreenFactory, onChanged: () -> Unit): RecurringOccurrenceViewModel =
    viewModel(factory = viewModelFactory {
        initializer {
            RecurringOccurrenceViewModel(factory.recurringRepository.occurrences, factory.repository, onChanged)
        }
    })

@Composable
internal fun RecurringOccurrenceHost(model: RecurringOccurrenceViewModel, repository: ExpenseRepository, items: List<RecurringItem>,
    onOpenExpense: (Long) -> Unit, onRecordPayment: (RecurringPaymentOrigin) -> Unit) {
    val state by model.uiState.collectAsStateWithLifecycle()
    var selectionJson by rememberSaveable { mutableStateOf<String?>(null) }
    val selection = readRecurringPaymentOrigin(selectionJson)
    val original by remember(selection?.clientRef) {
        selection?.clientRef?.let(repository::observeManualExpense) ?: flowOf(null)
    }.collectAsStateWithLifecycle(initialValue = null)
    val lifecycle by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { model.refresh() }
    LaunchedEffect(state.item?.publicId, state.occurrence?.period) {
        val item = state.item ?: return@LaunchedEffect
        val binding = state.access?.binding ?: return@LaunchedEffect
        val period = state.occurrence?.period ?: state.requestedPeriod
        val samePeriod = selection?.binding == binding && selection.seriesPublicId == item.publicId && selection.period == period
        selectionJson = recurringPaymentOriginJson(RecurringPaymentOrigin(binding, item.publicId, period,
            clientRef = selection?.clientRef.takeIf { samePeriod }))
    }
    LaunchedEffect(selectionJson, state.access?.binding, items) {
        if (state.item == null && selection?.binding == state.access?.binding) {
            items.firstOrNull { it.publicId == selection?.seriesPublicId }?.let { model.open(it, checkNotNull(selection).period) }
        }
    }
    if (!lifecycle.isAtLeast(Lifecycle.State.RESUMED)) return
    RecurringOccurrenceSheet(state, OccurrenceSheetActions(
        onDismiss = { if (!state.saving) { selectionJson = null; model.dismiss() } },
        onRefresh = model::refresh,
        onPeriod = model::changePeriod,
        onChoose = model::choose,
        onSubmit = model::submit,
        onRecover = model::recover,
        onOpenExpense = onOpenExpense,
        onRecordPayment = {
            val origin = selection ?: return@OccurrenceSheetActions
            val payment = origin.copy(clientRef = origin.clientRef ?: UUID.randomUUID().toString())
            selectionJson = recurringPaymentOriginJson(payment)
            onRecordPayment(payment)
        },
    ), preferredExpenseId = original?.acceptedExpenseId)
}
