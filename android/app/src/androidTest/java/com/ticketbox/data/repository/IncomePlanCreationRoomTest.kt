package com.ticketbox.data.repository

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.IncomePlanScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.IncomePlanEditViewModel
import com.ticketbox.viewmodel.IncomePlanViewModel
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class IncomePlanCreationRoomTest {
    @get:Rule val compose = createComposeRule()
    private val fixture = IncomePlanConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    private val model = mutableStateOf<IncomePlanViewModel?>(null)
    private val editor = mutableStateOf<IncomePlanEditViewModel?>(null)

    @After fun close() { stopModels(); fixture.close() }

    @Test fun actualCreateSheetPublishesOriginalJpyAndReplaysAfterOctoberReopen() {
        fixture.network.forecastCurrencyCode = "JPY"
        installModels()
        compose.setContent {
            val current = model.value ?: return@setContent
            val edit = editor.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) { IncomePlanScreen(current, edit, {}) }
        }
        compose.waitUntil(10_000) { model.value?.state?.value?.forecastMonth == "2026-09" }
        compose.onNodeWithText("添加").performScrollTo().performClick()
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextInput("旅行补贴")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextInput("1200")
        compose.onNodeWithText("保存").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 }
        val original = fixture.stored().single()
        assertEquals(0, fixture.network.creationCalls.size)
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        stopModels()
        fixture.advanceToOctober()
        fixture.network.forecastCurrencyCode = "CNY"
        fixture.network.failReads = true
        installModels()
        compose.waitUntil(10_000) { model.value?.state?.value?.pendingSubmissions?.size == 1 }
        compose.onNodeWithText("旅行补贴 · 2026-09").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("重试原提交").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
        fixture.network.loseResponse = false
        assertEquals(1, runBlocking { fixture.drain() }.done)
        assertEquals(2, fixture.network.creationCalls.size)
        assertEquals(fixture.network.creationCalls.first(), fixture.network.creationCalls.last())
        assertEquals("JPY", fixture.network.creationCalls.last().first.homeCurrencyCode)
        assertEquals(1200L, fixture.network.creationCalls.last().first.amountCents)
        assertEquals(original["idempotencyKey"], fixture.network.creationCalls.last().second)
        assertEquals(original["payload"], fixture.stored().single()["payload"])
        assertEquals(1, fixture.network.creationReceipts.size)
    }

    private fun installModels() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            model.value = IncomePlanViewModel(graph.incomePlanRepository)
            editor.value = IncomePlanEditViewModel(graph.incomePlanRepository)
        }
    }

    private fun stopModels() = compose.runOnIdle {
        model.value?.viewModelScope?.cancel()
        editor.value?.viewModelScope?.cancel()
    }
}
