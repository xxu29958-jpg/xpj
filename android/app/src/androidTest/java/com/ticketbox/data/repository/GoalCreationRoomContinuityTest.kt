package com.ticketbox.data.repository

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.RuntimeCompatibilityDto
import com.ticketbox.data.remote.dto.RuntimeCurrencyCapabilityDto
import com.ticketbox.data.remote.dto.RuntimeProductCapabilitiesDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.CreateSpendingGoalScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.CreateSpendingGoalViewModel
import java.io.IOException
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class GoalCreationRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val network = DebtAdjustmentConnectedNetwork()
    private var currency = "JPY"
    private var loseAck = true
    private var navigations = 0
    private val keys = mutableListOf<String?>()
    private val accepted = mutableMapOf<String, GoalDto>()
    private val service = object : ApiService by network.service {
        override suspend fun runtimeCompatibility() = RuntimeCompatibilityDto(CURRENT_TICKETBOX_API_VERSION, "compatible",
            RuntimeProductCapabilitiesDto(RuntimeCurrencyCapabilityDto("1:1:$currency", currency, if (currency == "JPY") 0 else 2, "compatible")))
        override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?, idempotencyKey: String?): GoalDto {
            keys += idempotencyKey
            val receipt = accepted.getOrPut(requireNotNull(idempotencyKey)) {
                check(request.homeCurrencyCode == "JPY" && request.targetAmountCents == 1200L)
                GoalDto("goal-created", "debt-adjustment-ledger", request.name, request.goalType, request.period,
                    request.month, request.category, request.targetAmountCents, 0, request.targetAmountCents, 0, "not_started", "active",
                    "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 1, null, homeCurrencyCode = "JPY")
            }
            if (loseAck) throw IOException("Synthetic lost acknowledgement")
            return receipt
        }
    }
    private val fixture = DebtAdjustmentConnectedFixture(context, service)
    private var currentModel by mutableStateOf<CreateSpendingGoalViewModel?>(null)
    private val model: CreateSpendingGoalViewModel get() = requireNotNull(currentModel)

    @After fun close() {
        if (currentModel != null) compose.runOnIdle { model.viewModelScope.cancel() }
        fixture.close()
    }

    @Test fun realCreateSurvivesRoomReopenAndReplaysOneOriginalAfterAcknowledgementLoss() {
        currentModel = CreateSpendingGoalViewModel(fixture.reopen().goalEditRepository)
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) {
            CreateSpendingGoalScreen(model, "2026-09", {}, { navigations += 1 })
        } }
        compose.waitUntil(10_000) { model.state.value.ledgerCurrency != null }
        compose.runOnIdle { model.updateName("旅行"); model.updateTargetAmount("1200") }
        compose.onNodeWithText(context.getString(R.string.spending_goal_create_save)).performClick()
        compose.waitUntil(10_000) { model.state.value.pending != null }
        val original = fixture.stored().single()
        assertEquals(0, keys.size)
        assertEquals(0, navigations)
        runBlocking { assertEquals(1, engine().drainOnce().failures) }
        compose.waitUntil(10_000) { model.state.value.pending?.canRetry == true }
        compose.runOnIdle { model.viewModelScope.cancel() }
        currency = "CNY"
        val graph = fixture.reopen()
        compose.runOnIdle { currentModel = CreateSpendingGoalViewModel(graph.goalEditRepository) }
        compose.waitUntil(10_000) { model.state.value.pending?.canRetry == true }
        assertEquals("JPY", model.state.value.ledgerCurrency?.storageKey)
        assertEquals("1200", model.state.value.targetAmountInput)
        assertEquals(original["payload"], fixture.stored().single()["payload"])
        loseAck = false
        compose.onNodeWithText(context.getString(R.string.spending_goal_submission_retry)).performClick()
        compose.waitUntil(10_000) { !model.state.value.isSubmitting }
        runBlocking { assertEquals(1, engine().drainOnce().done) }
        compose.waitUntil(10_000) { navigations == 1 }
        assertEquals(1, accepted.size)
        assertEquals(listOf(original["idempotencyKey"], original["idempotencyKey"]), keys)
        assertEquals(original["payload"], fixture.stored().single()["payload"])
        check(!fixture.stored().single()["receiptJson"].isNullOrBlank())
    }

    private fun engine(): OutboxDrainEngine {
        val adapters = OutboxAdapterGraph()
        return OutboxDrainEngine(fixture.outbox, listOf(CreateGoalDispatcher({ service }, adapters.goalCreateAdapter,
            adapters.goalReceiptAdapter)), maxAttempts = 1,
            now = { java.time.Instant.parse("2026-09-30T15:30:00Z").toEpochMilli() })
    }
}
