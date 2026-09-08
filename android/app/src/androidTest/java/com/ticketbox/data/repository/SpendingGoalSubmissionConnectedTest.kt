package com.ticketbox.data.repository

import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.plan.SpendingGoalDetailScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel
import com.ticketbox.viewmodel.SpendingGoalEditField
import java.io.IOException
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.flow.first
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.dto.RuntimeCompatibilityDto
import com.ticketbox.data.remote.dto.RuntimeProductCapabilitiesDto
import com.ticketbox.data.remote.dto.RuntimeCurrencyCapabilityDto
import com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class SpendingGoalSubmissionConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val debtNetwork = DebtAdjustmentConnectedNetwork()
    private val original = GoalDto(
        publicId = "spending-goal-original", ledgerId = "debt-adjustment-ledger", name = "本月餐饮",
        goalType = "spending_limit", period = "monthly", month = "2026-09", category = "餐饮",
        targetAmountCents = 20_000, spentAmountCents = 8_000, remainingAmountCents = 12_000,
        progressPercent = 40, progressState = "on_track", status = "active", rowVersion = 2,
        createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-02T00:00:00Z", archivedAt = null,
    )
    private var remoteWrites = 0
    private var loseAck = true
    private var failRead = false
    private var canonical = original
    private val keys = mutableListOf<String?>()
    private val committed = mutableMapOf<String, GoalDto>()
    private val service = object : ApiService by debtNetwork.service {
        override suspend fun runtimeCompatibility() = RuntimeCompatibilityDto(CURRENT_TICKETBOX_API_VERSION,
            "compatible", RuntimeProductCapabilitiesDto(RuntimeCurrencyCapabilityDto("1:1:CNY", "CNY", 2, "compatible")))
        override suspend fun goal(publicId: String, timezone: String?): GoalDto {
            check(publicId == original.publicId)
            if (failRead) throw IOException("Synthetic unavailable goal read")
            return canonical
        }

        override suspend fun updateGoal(publicId: String, request: GoalUpdateRequestDto,
            idempotencyKey: String?, timezone: String?): GoalDto {
            remoteWrites += 1
            keys += idempotencyKey
            val result = committed.getOrPut(requireNotNull(idempotencyKey)) {
                check(request.expectedRowVersion == original.rowVersion)
                original.copy(targetAmountCents = 35_000, remainingAmountCents = 27_000, rowVersion = 3).also { canonical = it }
            }
            if (loseAck) throw IOException("Synthetic lost acknowledgement")
            return result
        }
    }
    private val fixture = DebtAdjustmentConnectedFixture(context, service)
    private lateinit var model: SpendingGoalDetailViewModel

    @After fun close() {
        if (::model.isInitialized) compose.runOnIdle { model.viewModelScope.cancel() }
        fixture.close()
    }

    @Test
    fun realSavePublishesTheOriginalGoalIntentBeforeRemoteIo() {
        openAndSave()

        val rows = fixture.stored().filter { it["targetId"] == "goal:${original.publicId}" }
        assertEquals("Save must preserve one original submission in Room", 1, rows.size)
        assertEquals("Only the existing dispatcher may perform remote writes", 0, remoteWrites)
        assertEquals("The server-confirmed goal must not become an optimistic total", 20_000L,
            model.state.value.goal?.targetAmountCents)
        compose.runOnIdle { model.viewModelScope.cancel() }
        fixture.reopen()
        assertEquals(rows, fixture.stored().filter { it["targetId"] == "goal:${original.publicId}" })
    }

    @Test
    fun retryFromRoomPreservesTheOriginalKeyAndCanonicalReceiptAfterReentry() {
        openAndSave()
        val originalRow = fixture.stored().single()
        val adapters = OutboxAdapterGraph()
        fun engine() = OutboxDrainEngine(fixture.outbox, listOf(UpdateGoalDispatcher({ service },
            adapters.goalUpdateAdapter, adapters.goalReceiptAdapter)), maxAttempts = 1,
            now = { java.time.Instant.parse("2026-09-30T15:30:00Z").toEpochMilli() })
        runBlocking { assertEquals(1, engine().drainOnce().failures) }
        compose.waitUntil(10_000) { model.state.value.pendingEdits.any { it.canRetry } }
        loseAck = false
        compose.onNodeWithText("重试原提交").performClick()
        compose.waitUntil(10_000) { !model.state.value.isSaving }
        runBlocking { assertEquals(1, engine().drainOnce().done) }
        assertEquals(listOf(originalRow["idempotencyKey"], originalRow["idempotencyKey"]), keys)
        assertEquals(1, committed.size)
        compose.runOnIdle { model.viewModelScope.cancel() }
        val graph = fixture.reopen()
        failRead = true
        model = SpendingGoalDetailViewModel(graph.reportsRepository, graph.goalEditRepository)
        model.load(original.publicId)
        compose.waitUntil(10_000) { model.state.value.goal?.rowVersion == 3L && !model.state.value.isLoading }
        assertEquals(35_000L, model.state.value.goal?.targetAmountCents)
        assertEquals(27_000L, model.state.value.goal?.remainingAmountCents)
        val stored = fixture.stored().single()
        assertEquals(originalRow["payload"], stored["payload"])
        assertEquals(originalRow["idempotencyKey"], stored["idempotencyKey"])
        check(!stored["receiptJson"].isNullOrBlank())
    }

    private fun openAndSave() {
        val graph = fixture.reopen()
        model = SpendingGoalDetailViewModel(graph.reportsRepository, graph.goalEditRepository)
        model.load(original.publicId)
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) { SpendingGoalDetailScreen(model, {}) } }
        compose.waitUntil(10_000) { model.state.value.goal != null }
        compose.onNodeWithText(context.getString(R.string.spending_goal_edit_action)).performClick()
        compose.runOnIdle { model.updateField(SpendingGoalEditField.Amount, "350.00") }
        compose.onNodeWithText(context.getString(R.string.spending_goal_edit_save)).performClick()
        compose.waitUntil(10_000) { !model.state.value.isSaving }

    }

}
