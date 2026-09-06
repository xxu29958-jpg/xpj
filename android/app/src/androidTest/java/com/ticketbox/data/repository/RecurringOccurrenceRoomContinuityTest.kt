package com.ticketbox.data.repository

import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertTextEquals
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
}
