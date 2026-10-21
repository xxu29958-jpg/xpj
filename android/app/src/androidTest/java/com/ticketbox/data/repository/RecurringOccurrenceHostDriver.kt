package com.ticketbox.data.repository

import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.RepositoryGraph
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.navigation.RecurringExpenseNavigation
import com.ticketbox.ui.navigation.RecurringOccurrenceHost
import com.ticketbox.ui.navigation.RecurringPaymentDraftStore
import com.ticketbox.ui.navigation.RecurringPaymentRestore
import com.ticketbox.ui.navigation.RecurringPaymentTask
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.job
import kotlinx.coroutines.runBlocking

/** Shared Host assembly: binding, Outbox graph, Host, rebuild. */
internal class RecurringOccurrenceHostDriver(
    private val compose: androidx.compose.ui.test.junit4.ComposeContentTestRule,
    val fixture: RecurringOccurrenceConnectedFixture,
) {
    val model = mutableStateOf<RecurringOccurrenceViewModel?>(null)
    val openedExpenses = mutableListOf<Long>()
    var graph: RepositoryGraph? = null
    val paymentTask = mutableStateOf<RecurringPaymentTask?>(null)
    val openedPayments = mutableListOf<RecurringPaymentTask>()
    val openedSubmissions = mutableListOf<String>()
    val ledgerToday = mutableStateOf<java.time.LocalDate?>(null)

    fun close() {
        stopModel()
        fixture.close()
    }

    fun stopModel() {
        val previous = compose.runOnIdle { model.value.also { model.value = null } } ?: return
        compose.waitForIdle()
        runBlocking { previous.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    fun installModel(open: Boolean = true, savedState: SavedStateHandle = SavedStateHandle()) {
        stopModel()
        val graph = fixture.reopen()
        this.graph = graph
        compose.runOnIdle {
            model.value = RecurringOccurrenceViewModel(
                graph.recurringRepository.occurrences,
                fixture.ledger,
                fixture.debts,
                savedStateHandle = savedState,
            ).also { if (open) it.open(occurrenceConnectedItem()) }
        }
    }

    fun showOccurrenceHost(
        drafts: RecurringPaymentDraftStore = RecurringPaymentDraftStore(SavedStateHandle()),
        hostOpen: androidx.compose.runtime.State<Boolean>? = null,
    ) {
        compose.setContent {
            val current = model.value ?: return@setContent
            if (hostOpen != null && !hostOpen.value) return@setContent
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceHost(
                    current,
                    requireNotNull(graph).expenseRepository.manualCreation,
                    RecurringExpenseNavigation(
                        { openedExpenses += it },
                        { paymentTask.value = it; openedPayments += it },
                        { openedSubmissions += it },
                    ),
                    RecurringPaymentRestore(items = listOf(occurrenceConnectedItem()), drafts = drafts),
                    ledgerToday = ledgerToday.value,
                )
            }
        }
    }
}
