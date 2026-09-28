package com.ticketbox.data.repository

import android.os.Bundle
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.SAVED_STATE_REGISTRY_OWNER_KEY
import androidx.lifecycle.VIEW_MODEL_STORE_OWNER_KEY
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.MutableCreationExtras
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.RuntimeCompatibilityDto
import com.ticketbox.data.remote.dto.RuntimeCurrencyCapabilityDto
import com.ticketbox.data.remote.dto.RuntimeProductCapabilitiesDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.ui.screens.CreateSpendingGoalScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.CreateSpendingGoalViewModel
import com.ticketbox.viewmodel.createSpendingGoalViewModelFactory
import java.io.IOException
import kotlinx.coroutines.cancel
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
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
    private var stateOwner: IncomeDraftStateOwner? = null
    private var savedState: Bundle? = null
    private var localAcknowledgement: CompletableDeferred<Unit>? = null

    @After fun close() {
        localAcknowledgement?.complete(Unit)
        if (currentModel != null) compose.runOnIdle { model.viewModelScope.cancel(); stateOwner?.viewModelStore?.clear() }
        fixture.close()
    }

    @Test fun realCreateSurvivesRoomReopenAndReplaysOneOriginalAfterAcknowledgementLoss() {
        installModel(fixture.reopen().goalEditRepository)
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) {
            CreateSpendingGoalScreen(model, "2026-09", {}, { navigations += 1 })
        } }
        compose.waitUntil(10_000) { model.state.value.editable && model.state.value.ledgerCurrency != null }
        compose.runOnIdle { model.updateName("旅行"); model.updateTargetAmount("1200") }
        compose.onNodeWithText(context.getString(R.string.spending_goal_create_save)).performClick()
        compose.waitUntil(10_000) { model.state.value.pending != null }
        val original = fixture.stored().single()
        assertEquals(0, keys.size)
        assertEquals(0, navigations)
        runBlocking { assertEquals(1, engine().drainOnce().failures) }
        compose.waitUntil(10_000) { model.state.value.pending?.canRetry == true }
        saveAndStopModel()
        currency = "CNY"
        val graph = fixture.reopen()
        installModel(graph.goalEditRepository)
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

    @Test fun oldSystemDraftSnapshotFindsTheRoomAcceptedKeyWithoutReinterpretingJpyOrCreatingAgain() {
        localAcknowledgement = CompletableDeferred()
        installModel(fixture.reopen().goalEditRepository)
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) {
            CreateSpendingGoalScreen(model, "2026-09", {}, { navigations += 1 })
        } }
        compose.waitUntil(10_000) { model.state.value.editable && model.state.value.ledgerCurrency?.storageKey == "JPY" }
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextReplacement("  旅行原稿  ")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextReplacement("1200.0")
        closeSoftKeyboard()
        compose.waitForIdle()
        val originalKey = model.state.value.creationKey
        val beforeSave = compose.runOnIdle { requireNotNull(stateOwner).save() }
        assertTrue(model.state.value.canSubmit)
        compose.onNodeWithText(context.getString(R.string.spending_goal_create_save)).performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 && model.state.value.isSubmitting }
        val acceptedRow = fixture.stored().single()
        assertEquals(originalKey, acceptedRow["idempotencyKey"])
        assertTrue(keys.isEmpty())
        saveAndStopModel()
        savedState = beforeSave
        currency = "CNY"
        installModel(fixture.reopen().goalEditRepository)
        compose.waitUntil(10_000) { model.state.value.pending?.row?.id == acceptedRow["id"]?.toLong() }
        assertEquals("JPY", model.state.value.ledgerCurrency?.storageKey)
        assertEquals("2026-09", model.state.value.month)
        assertEquals("1200", model.state.value.targetAmountInput)
        assertEquals(listOf(acceptedRow), fixture.stored())
        assertEquals(0, navigations)
        assertTrue(keys.isEmpty())
        loseAck = false
        runBlocking { assertEquals(1, engine().drainOnce().done) }
        compose.waitUntil(10_000) { navigations == 1 }
        assertEquals(listOf(originalKey), keys)
        assertEquals(1, accepted.size)
        assertEquals(acceptedRow["payload"], fixture.stored().single()["payload"])
    }

    @Test fun unknownOriginalAfterReopenKeepsRawDraftVisibleWithoutClaimingItWillSync() {
        localAcknowledgement = CompletableDeferred()
        installModel(fixture.reopen().goalEditRepository)
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) {
            CreateSpendingGoalScreen(model, "2026-09", {}, { navigations += 1 })
        } }
        compose.waitUntil(10_000) { model.state.value.editable && model.state.value.ledgerCurrency?.storageKey == "JPY" }
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextReplacement("  旅行原稿  ")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextReplacement("1200.0")
        closeSoftKeyboard()
        compose.waitForIdle()
        val originalKey = model.state.value.creationKey
        val beforeSave = compose.runOnIdle { requireNotNull(stateOwner).save() }
        assertTrue(model.state.value.canSubmit)
        compose.onNodeWithText(context.getString(R.string.spending_goal_create_save)).performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 && model.state.value.isSubmitting }
        val acceptedRow = fixture.stored().single()
        saveAndStopModel()
        fixture.setStoredMutationStatus(requireNotNull(acceptedRow["id"]).toLong(), "future_goal_state")
        val unresolvedRow = fixture.stored().single()
        savedState = beforeSave
        currency = "CNY"
        installModel(fixture.reopen().goalEditRepository)
        compose.waitUntil(10_000) { model.state.value.pending?.row?.status == PendingMutationStatus.Unknown }
        compose.onNodeWithText(context.getString(R.string.goal_creation_unrecognized)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("  旅行原稿  ").performScrollTo().assertIsDisplayed().assertIsNotEnabled()
        compose.onNodeWithText("1200.0").performScrollTo().assertIsDisplayed().assertIsNotEnabled()
        compose.onNodeWithText(context.getString(R.string.spending_goal_create_save)).assertIsNotEnabled()
        assertEquals(originalKey, model.state.value.creationKey)
        assertEquals("JPY", model.state.value.ledgerCurrency?.storageKey)
        assertEquals("2026-09", model.state.value.month)
        assertEquals(listOf(unresolvedRow), fixture.stored())
        assertEquals(acceptedRow["payload"], unresolvedRow["payload"])
        assertEquals(0, navigations)
        assertTrue(keys.isEmpty())
    }

    private fun installModel(repository: GoalEditActions) {
        val actions = object : GoalEditActions by repository {
            override suspend fun create(binding: LogicalSessionBinding, request: com.ticketbox.data.remote.dto.GoalCreateRequestDto,
                creationKey: String): Result<Long> {
                val result = repository.create(binding, request, creationKey)
                if (result.isSuccess) localAcknowledgement?.await()
                return result
            }
        }
        compose.runOnIdle {
            val owner = IncomeDraftStateOwner(savedState).also { stateOwner = it }
            val extras = MutableCreationExtras().apply {
                set(SAVED_STATE_REGISTRY_OWNER_KEY, owner)
                set(VIEW_MODEL_STORE_OWNER_KEY, owner)
            }
            currentModel = ViewModelProvider(owner.viewModelStore, createSpendingGoalViewModelFactory(actions), extras)[
                "create-spending-goal", CreateSpendingGoalViewModel::class.java]
        }
    }

    private fun saveAndStopModel() = compose.runOnIdle {
        savedState = requireNotNull(stateOwner).save()
        requireNotNull(stateOwner).viewModelStore.clear()
    }

    private fun engine(): OutboxDrainEngine {
        val adapters = OutboxAdapterGraph()
        return OutboxDrainEngine(fixture.outbox, listOf(CreateGoalDispatcher({ service }, adapters.goalCreateAdapter,
            adapters.goalReceiptAdapter, fixture.graph.reportsRepository::invalidateGoalReadsAfterDelivery)), maxAttempts = 1,
            now = { java.time.Instant.parse("2026-09-30T15:30:00Z").toEpochMilli() })
    }
}
