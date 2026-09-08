package com.ticketbox.data.repository

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.screens.IncomePlanScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.IncomePlanEditViewModel
import com.ticketbox.viewmodel.IncomePlanLoadState
import com.ticketbox.viewmodel.IncomePlanViewModel
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class IncomePlanRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val fixture = IncomePlanConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    private val model = mutableStateOf<IncomePlanViewModel?>(null)
    private val editor = mutableStateOf<IncomePlanEditViewModel?>(null)

    @After
    fun close() { stopModels(); fixture.close() }

    @Test
    fun realEditorSurvivesRoomReopenFailedReadAndOctoberReplay() {
        installModels()
        compose.setContent {
            val current = model.value ?: return@setContent
            val edit = editor.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) { IncomePlanScreen(current, edit, CurrencyDisplay.Base, {}) }
        }
        compose.waitUntil(10_000) { model.value?.state?.value?.activePlans?.size == 1 }
        compose.onNodeWithText("九月工资计划").performScrollTo().performClick()
        compose.waitUntil(10_000) { editor.value?.state?.value?.session?.draft?.homeCurrency != null }
        compose.onNodeWithText("100.00").performScrollTo().performTextReplacement("120.00")
        compose.onNodeWithText("保存").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 }
        val original = fixture.stored().single()
        assertEquals(0, fixture.network.calls.size)
        assertEquals("income-ledger", original["ledgerId"])
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        assertEquals(1, fixture.network.results.size)
        reopenInOctober(original)
        compose.onNodeWithText("九月工资计划 · 2026-09").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("重试原提交").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
        fixture.network.loseResponse = false
        assertEquals(1, runBlocking { fixture.drain() }.done)
        assertEquals(2, fixture.network.calls.size)
        assertEquals(fixture.network.calls.first(), fixture.network.calls.last())
        assertEquals("2026-09", fixture.network.calls.last().first.intentMonth)
        assertEquals(original["idempotencyKey"], fixture.network.calls.last().second)
        assertEquals(1, fixture.network.results.size)
        fixture.network.failReads = false
        compose.runOnIdle { model.value?.refresh() }
        compose.waitUntil(10_000) { model.value?.state?.value?.forecastMonth == "2026-10" }
        assertEquals(12_000L, model.value?.state?.value?.currentMonthSummary?.expectedAmountCents)
        compose.onNodeWithText("2026-10 预计收入").performScrollTo().assertIsDisplayed()
    }

    private fun reopenInOctober(original: Map<String, String?>) {
        stopModels()
        fixture.advanceToOctober()
        fixture.network.failReads = true
        installModels()
        compose.waitUntil(10_000) { model.value?.state?.value?.loadState == IncomePlanLoadState.Failed &&
            model.value?.state?.value?.pendingEdits?.size == 1 }
        val reopened = fixture.stored().single()
        for (key in listOf("payload", "expectedRowVersion", "idempotencyKey", "ownerKey", "ledgerId")) {
            assertEquals(original[key], reopened[key])
        }
    }

    private fun installModels() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            model.value = IncomePlanViewModel(graph.incomePlanRepository)
            editor.value = IncomePlanEditViewModel(graph.incomePlanRepository,
                onDataChanged = { model.value?.refresh() })
        }
    }

    private fun stopModels() = compose.runOnIdle {
        model.value?.viewModelScope?.cancel()
        editor.value?.viewModelScope?.cancel()
    }
}
