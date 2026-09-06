package com.ticketbox.data.repository

import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class RecurringOccurrenceRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val fixture = RecurringOccurrenceConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    private val model = mutableStateOf<RecurringOccurrenceViewModel?>(null)
    private val openedExpenses = mutableListOf<Long>()

    @After
    fun close() {
        compose.runOnIdle { model.value?.viewModelScope?.cancel() }
        fixture.close()
    }

    @Test
    fun userSelectionSurvivesRoomRestartAndUnknownResponseThenExplicitUndo() {
        installModel()
        compose.setContent {
            val current = model.value ?: return@setContent
            val state by current.uiState.collectAsState()
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceSheet(state, CurrencyDisplay.Base, OccurrenceSheetActions(
                    current::dismiss, current::refresh, current::changePeriod,
                    { current.choose(it, CurrencyCode.CNY) }, current::submit, current::recover,
                    onOpenExpense = { openedExpenses += it },
                ))
            }
        }
        compose.waitUntil(10_000) { model.value?.uiState?.value?.canWrite == true }
        compose.onNodeWithTag("occurrence-state").assertTextEquals("本期尚未履约")
        compose.onNodeWithTag("occurrence-payment-1").performScrollTo().performClick()
        compose.onNodeWithTag("occurrence-submit").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 }
        val original = fixture.stored().single()
        assertEquals(0, fixture.network.calls.size)
        assertEquals("set_recurring_occurrence_payment", original["type"])
        assertEquals("recurring-ledger", original["ledgerId"])
        assertEquals("unfulfilled", model.value?.uiState?.value?.occurrence?.state)

        compose.runOnIdle { model.value?.viewModelScope?.cancel() }
        fixture.reopen()
        assertEquals(original, fixture.stored().single())
        assertEquals(1, runBlocking { fixture.drain() }.retryable)
        fixture.advanceForRetry()
        fixture.network.loseResponse = false
        installModel()
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { model.value?.uiState?.value?.occurrence?.state == "fulfilled" }
        assertEquals(2, fixture.network.calls.size)
        assertEquals(fixture.network.calls.first(), fixture.network.calls.last())
        assertEquals(original["idempotencyKey"], fixture.network.calls.last().second)
        assertEquals(0L, model.value?.uiState?.value?.occurrence?.reservedAmountCents)
        compose.onNodeWithText("查看关联账单").performScrollTo().performClick()
        assertEquals(listOf(1L), openedExpenses)
        completeUndo()
    }

    private fun completeUndo() {
        compose.waitUntil(10_000) { model.value?.uiState?.value?.canWrite == true }
        compose.onNodeWithText("撤销本期关联").performScrollTo().performClick()
        compose.onNodeWithTag("occurrence-submit").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 2 }
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { model.value?.uiState?.value?.occurrence?.state == "unfulfilled" }
        assertEquals(10_000L, model.value?.uiState?.value?.occurrence?.reservedAmountCents)
        assertEquals("2026-09-05", model.value?.uiState?.value?.occurrence?.nextDueDate)
        assertEquals("clear", fixture.network.calls.last().first.action)
    }

    private fun installModel() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            model.value = RecurringOccurrenceViewModel(graph.recurringRepository.occurrences, fixture.ledger, fixture.outbox)
                .also { it.open(occurrenceConnectedItem()) }
        }
    }

    @Test
    fun savedPriorPeriodCanBeIdentifiedWhenReopenedWithUnavailablePeriodRead() {
        val graph = fixture.reopen()
        val actions = graph.recurringRepository.occurrences
        val binding = requireNotNull(actions.currentAccess()).binding
        val prior = fixture.network.current.copy(period = "2026-08")
        fixture.network.current = prior
        runBlocking {
            actions.enqueue(binding, OccurrencePaymentDraft(prior, "八月房租",
                com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto("link", 0, 7, "payment-august", 2),
                "八月完整付款", 9_800, CurrencyCode.CNY)).getOrThrow()
        }
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failed)
        val originalKey = fixture.stored().single()["idempotencyKey"]
        fixture.network.failReads = true
        installModel()
        compose.setContent {
            val current = model.value ?: return@setContent
            val state by current.uiState.collectAsState()
            TicketboxTheme(skin = AppSkin.Paper) {
                RecurringOccurrenceSheet(state, CurrencyDisplay.Base, OccurrenceSheetActions(
                    current::dismiss, current::refresh, current::changePeriod,
                    { current.choose(it, CurrencyCode.CNY) }, current::submit, current::recover,
                ))
            }
        }
        compose.waitUntil(10_000) { model.value?.uiState?.value?.seriesPending?.size == 1 && model.value?.uiState?.value?.loading == false }
        compose.onNodeWithText("八月房租 · 2026-08").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("八月完整付款", substring = true).performScrollTo().assertIsDisplayed()
        assertEquals(null, model.value?.uiState?.value?.occurrence)
        assertEquals(1, fixture.network.calls.size)
        val pending = model.value!!.uiState.value.seriesPending.single()
        assertEquals("2026-08", pending.intent?.period)
        assertEquals(2L, pending.intent?.request?.expectedExpenseRowVersion)
        fixture.network.loseResponse = false
        compose.onNodeWithText("重试原提交").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
        assertEquals(1, runBlocking { fixture.drain() }.done)
        assertEquals(2, fixture.network.calls.size)
        assertEquals(fixture.network.calls.first(), fixture.network.calls.last())
        assertEquals(originalKey, fixture.network.calls.last().second)
        assertEquals(1, fixture.network.results.size)
    }
}
