package com.ticketbox.data.repository

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.ComposeContentTestRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.RepositoryGraph
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.navigation.LEGACY_PERIOD_PAYMENT_SESSIONS_KEY
import com.ticketbox.ui.navigation.RecurringExpenseNavigation
import com.ticketbox.ui.navigation.RecurringOccurrenceHost
import com.ticketbox.ui.navigation.RecurringPaymentDraftStore
import com.ticketbox.ui.navigation.RecurringPaymentIdentity
import com.ticketbox.ui.navigation.RecurringPaymentRestore
import com.ticketbox.ui.navigation.RecurringPaymentTask
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import kotlinx.coroutines.cancel

internal data class LeftoverHostScene(
    val binding: LogicalSessionBinding,
    val leftover: SavedStateHandle,
    val drafts: RecurringPaymentDraftStore,
    val seen: Long,
    val generation: Long,
)

/** Shared leftover Host assembly: binding, leftover JSON, Outbox graph, Host, generation, rebuild. */
internal class RecurringOccurrenceHostDriver(
    private val compose: ComposeContentTestRule,
    val fixture: RecurringOccurrenceConnectedFixture,
) {
    val model = mutableStateOf<RecurringOccurrenceViewModel?>(null)
    val openedExpenses = mutableListOf<Long>()
    var graph: RepositoryGraph? = null
    val paymentTask = mutableStateOf<RecurringPaymentTask?>(null)
    val openedPayments = mutableListOf<RecurringPaymentTask>()

    fun close() {
        leftoverInspectHold?.complete(Unit)
        leftoverInspectHold = null
        compose.runOnIdle { model.value?.viewModelScope?.cancel() }
        fixture.close()
    }

    fun installModel(open: Boolean = true, savedState: SavedStateHandle = SavedStateHandle()) {
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

    fun bindWritableSeptember(): LogicalSessionBinding {
        installModel()
        compose.waitUntil(10_000) {
            model.value?.uiState?.value?.canWrite == true &&
                model.value?.uiState?.value?.occurrence?.period == "2026-09"
        }
        return requireNotNull(graph).expenseRepository.captureDeferredLedgerBinding() ?: error("binding")
    }

    fun stopOccurrenceModel() {
        compose.runOnIdle { model.value?.viewModelScope?.cancel() }
    }

    fun leftoverHandle(
        binding: LogicalSessionBinding,
        vararg sessions: LegacyPeriodPaymentSession,
    ): SavedStateHandle = SavedStateHandle().also {
        it[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(*sessions)
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
                    RecurringExpenseNavigation({ openedExpenses += it }, { paymentTask.value = it; openedPayments += it }),
                    RecurringPaymentRestore(items = listOf(occurrenceConnectedItem()), drafts = drafts),
                )
            }
        }
    }

    fun waitLeftoverBlocked() {
        compose.waitUntil(10_000) {
            runCatching {
                compose.onNodeWithTag("occurrence-payment-leftover").performScrollTo().assertIsDisplayed()
            }.isSuccess
        }
    }

    fun bumpOccurrenceGenerationFrom(seen: Long) {
        fixture.network.current = fixture.network.current.copy(
            rowVersion = seen + 1,
            state = "fulfilled",
            reservedAmountCents = 0,
            expensePublicId = "payment-1",
            paidAmountCents = 12_345,
            expenseId = 1,
            paidHomeCurrencyCode = "JPY",
        )
        fixture.network.current = fixture.network.current.copy(
            rowVersion = seen + 2,
            state = "unfulfilled",
            reservedAmountCents = 10_000,
            expensePublicId = null,
            paidAmountCents = null,
            expenseId = null,
            paidHomeCurrencyCode = null,
        )
    }

    fun openHeldLeftover(
        bumpGeneration: Boolean = true,
        rememberSeen: Boolean = false,
        drafts: RecurringPaymentDraftStore = RecurringPaymentDraftStore(SavedStateHandle()),
        beforeShow: (LeftoverHostScene) -> Unit = {},
        sessions: (LogicalSessionBinding) -> List<LegacyPeriodPaymentSession>,
    ): LeftoverHostScene {
        val binding = bindWritableSeptember()
        val seen = requireNotNull(model.value?.uiState?.value?.occurrence?.rowVersion)
        stopOccurrenceModel()
        val leftover = leftoverHandle(binding, *sessions(binding).toTypedArray())
        if (rememberSeen) {
            leftover[requireNotNull(RecurringPaymentIdentity(binding, "recurring-1", "2026-09", seen).leftoverSeenKey())] = seen
        }
        if (bumpGeneration) bumpOccurrenceGenerationFrom(seen)
        installModel(savedState = leftover)
        val scene = LeftoverHostScene(binding, leftover, drafts, seen, fixture.network.current.rowVersion)
        beforeShow(scene)
        showOccurrenceHost(drafts)
        return scene
    }
}
