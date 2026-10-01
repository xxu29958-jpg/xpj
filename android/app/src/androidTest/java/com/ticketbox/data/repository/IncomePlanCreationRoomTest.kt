package com.ticketbox.data.repository

import android.os.Bundle
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.SAVED_STATE_REGISTRY_OWNER_KEY
import androidx.lifecycle.VIEW_MODEL_STORE_OWNER_KEY
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.MutableCreationExtras
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.IncomePlanScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.IncomePlanEditViewModel
import com.ticketbox.viewmodel.IncomePlanCreateViewModel
import com.ticketbox.viewmodel.IncomePlanCreationPhase
import com.ticketbox.viewmodel.incomePlanCreateViewModelFactory
import com.ticketbox.viewmodel.IncomePlanViewModel
import kotlinx.coroutines.cancel
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class IncomePlanCreationRoomTest {
    @get:Rule val compose = createComposeRule()
    private val fixture = IncomePlanConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    private val model = mutableStateOf<IncomePlanViewModel?>(null)
    private val editor = mutableStateOf<IncomePlanEditViewModel?>(null)
    private val creator = mutableStateOf<IncomePlanCreateViewModel?>(null)
    private var creatorOwner: IncomeDraftStateOwner? = null
    private var creatorSavedState: Bundle? = null
    private var creationAck: CompletableDeferred<Unit>? = null

    @After fun close() { creationAck?.complete(Unit); stopModels(); fixture.close() }

    @Test fun actualCreateSheetPublishesOriginalJpyAndReplaysAfterOctoberReopen() {
        fixture.network.forecastCurrencyCode = "JPY"
        installModels()
        showModels()
        compose.waitUntil(10_000) { model.value?.state?.value?.forecastMonth == "2026-09" }
        compose.onNodeWithText("添加").performScrollTo().performClick()
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextInput("旅行补贴")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextInput("1200")
        closeSoftKeyboard()
        compose.waitForIdle()
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

    @Test fun oldSystemDraftSnapshotRejoinsTheOriginalRoomCreationAfterLocalAckLoss() {
        fixture.network.forecastCurrencyCode = "JPY"
        creationAck = CompletableDeferred()
        installModels()
        showModels()
        compose.waitUntil(10_000) { model.value?.state?.value?.forecastMonth == "2026-09" }
        compose.onNodeWithText("添加").performScrollTo().performClick()
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextInput("旅行补贴")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextInput("1200")
        closeSoftKeyboard()
        compose.waitForIdle()
        val oldDraft = requireNotNull(creator.value?.state?.value?.session)
        val beforeSave = compose.runOnIdle { requireNotNull(creatorOwner).save() }
        compose.onNodeWithText("保存").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 && creator.value?.state?.value?.isSubmitting == true }
        val accepted = fixture.stored().single()
        assertEquals(oldDraft.creationKey, accepted["idempotencyKey"])
        assertTrue(fixture.network.creationCalls.isEmpty())
        stopModels()
        creatorSavedState = beforeSave
        fixture.advanceToOctober()
        fixture.network.forecastCurrencyCode = "CNY"
        fixture.network.failReads = true
        installModels()
        compose.waitUntil(10_000) { creator.value?.state?.value?.session == null &&
            model.value?.state?.value?.selectedSubmissionId == accepted["id"]?.toLong() &&
            model.value?.state?.value?.pendingSubmissions?.size == 1 }
        val pending = requireNotNull(model.value?.state?.value?.pendingSubmissions?.singleOrNull())
        assertEquals("JPY", pending.intent?.homeCurrencyCode)
        assertEquals(1200L, pending.intent?.originalAmountCents)
        assertEquals("2026-09", pending.intent?.request?.intentMonth)
        assertEquals("2026-09", pending.intent?.request?.incomeMonth)
        assertEquals(listOf(accepted), fixture.stored())
        assertTrue(fixture.network.creationCalls.isEmpty())
        compose.onNodeWithText("旅行补贴 · 2026-09").performScrollTo().assertIsDisplayed()
    }

    @Test fun collectedCompletedRecordRequiresExplicitDraftDiscardWithoutRepeatingTheAcceptedIncome() {
        creationAck = CompletableDeferred()
        installModels()
        showModels()
        compose.waitUntil(10_000) { model.value?.state?.value?.forecastMonth == "2026-09" }
        compose.onNodeWithText("添加").performScrollTo().performClick()
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextInput("已保存的补贴")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextInput("120.00")
        closeSoftKeyboard()
        compose.waitForIdle()
        compose.onNodeWithText("保存").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 && creator.value?.state?.value?.isSubmitting == true }
        val original = requireNotNull(creator.value?.state?.value?.session)
        fixture.network.loseResponse = false
        assertEquals(1, runBlocking { fixture.drain() }.done)
        stopModels() // The system retains Publishing before the local acknowledgement reaches its owner.
        compose.runOnIdle { model.value = null }
        compose.waitForIdle()
        fixture.advanceToOctober()
        val graph = fixture.reopen()
        runBlocking {
            val pending = requireNotNull(graph.incomePlanRepository.originalCreation(original.binding, original.creationKey).getOrThrow())
            assertTrue(pending.isConfirmed)
            assertEquals(1, fixture.outbox.gcCompleted(retentionMillis = 0))
        }
        assertTrue(fixture.stored().isEmpty())
        val acceptedIncome = fixture.network.creationReceipts.toMap()
        assertEquals(1, acceptedIncome.size)
        installModels()
        compose.waitUntil(10_000) { creator.value?.state?.value?.session?.phase == IncomePlanCreationPhase.NeedsRecovery }
        compose.onNodeWithText("添加").performScrollTo().performClick()
        compose.onNodeWithText("放弃草稿").performScrollTo().performClick()
        compose.onNodeWithText("取消").performClick()
        compose.onNodeWithText("已保存的补贴").performScrollTo().assertTextEquals("已保存的补贴").assertIsNotEnabled()
        assertEquals(original.creationKey, creator.value?.state?.value?.session?.creationKey)
        compose.onNodeWithText("放弃草稿").performScrollTo().performClick()
        compose.onNodeWithText("确认放弃").performClick()
        compose.onNodeWithText("添加").performScrollTo().performClick()
        assertEquals("", compose.onAllNodes(hasSetTextAction())[0].fetchSemanticsNode().config[SemanticsProperties.EditableText].text)
        assertEquals("", compose.onAllNodes(hasSetTextAction())[1].fetchSemanticsNode().config[SemanticsProperties.EditableText].text)
        assertNotEquals(original.creationKey, creator.value?.state?.value?.session?.creationKey)
        assertEquals(acceptedIncome, fixture.network.creationReceipts)
        assertEquals(1, fixture.network.creationCalls.size)
        assertTrue(fixture.stored().isEmpty())
    }

    private fun showModels() {
        compose.setContent {
            val current = model.value ?: return@setContent
            val edit = editor.value ?: return@setContent
            val create = creator.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) { IncomePlanScreen(current, edit, create, {}) }
        }
    }

    private fun installModels() {
        val graph = fixture.reopen()
        val repository = object : IncomePlanActions by graph.incomePlanRepository {
            override suspend fun create(expectedBinding: LogicalSessionBinding, draft: IncomePlanDraft,
                creationKey: String): Result<Long> {
                val result = graph.incomePlanRepository.create(expectedBinding, draft, creationKey)
                if (result.isSuccess) creationAck?.await()
                return result
            }
        }
        compose.runOnIdle {
            model.value = IncomePlanViewModel(repository)
            editor.value = IncomePlanEditViewModel(repository)
            val owner = IncomeDraftStateOwner(creatorSavedState).also { creatorOwner = it }
            val extras = MutableCreationExtras().apply {
                set(SAVED_STATE_REGISTRY_OWNER_KEY, owner)
                set(VIEW_MODEL_STORE_OWNER_KEY, owner)
            }
            creator.value = ViewModelProvider(owner.viewModelStore,
                incomePlanCreateViewModelFactory(repository), extras)["income-plan-create", IncomePlanCreateViewModel::class.java]
        }
    }

    private fun stopModels() = compose.runOnIdle {
        model.value?.viewModelScope?.cancel()
        editor.value?.viewModelScope?.cancel()
        creatorOwner?.let { creatorSavedState = it.save(); it.viewModelStore.clear() }
    }
}
