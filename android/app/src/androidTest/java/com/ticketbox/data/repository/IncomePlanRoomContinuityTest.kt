package com.ticketbox.data.repository

import android.os.Bundle
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.SAVED_STATE_REGISTRY_OWNER_KEY
import androidx.lifecycle.VIEW_MODEL_STORE_OWNER_KEY
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.enableSavedStateHandles
import androidx.lifecycle.viewmodel.MutableCreationExtras
import androidx.savedstate.SavedStateRegistryController
import androidx.savedstate.SavedStateRegistryOwner
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.IncomePlanScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.IncomePlanEditViewModel
import com.ticketbox.viewmodel.IncomePlanCreateViewModel
import com.ticketbox.viewmodel.IncomePlanLoadState
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.incomePlanEditViewModelFactory
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
    private val creator = mutableStateOf<IncomePlanCreateViewModel?>(null)
    private val editor = mutableStateOf<IncomePlanEditViewModel?>(null)
    private var editorStateOwner: IncomeDraftStateOwner? = null
    private var editorSavedState: Bundle? = null

    @After
    fun close() { stopModels(); fixture.close() }

    @Test
    fun realEditorSurvivesRoomReopenFailedReadAndOctoberReplay() {
        installModels()
        compose.setContent {
            val current = model.value ?: return@setContent
            val edit = editor.value ?: return@setContent
            val create = creator.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) { IncomePlanScreen(current, edit, create, {}) }
        }
        compose.waitUntil(10_000) { model.value?.state?.value?.activePlans?.size == 1 }
        compose.onNodeWithText("九月工资计划").performScrollTo().performClick()
        compose.waitUntil(10_000) { editor.value?.state?.value?.session?.draft?.homeCurrency != null }
        compose.onNodeWithText("100.00").performScrollTo().performTextReplacement("120.00")
        val draftBeforeLeaving = editor.value?.state?.value?.session
        stopModels()
        installModels()
        compose.waitUntil(10_000) { editor.value?.state?.value?.session != null }
        assertEquals(draftBeforeLeaving, editor.value?.state?.value?.session)
        assertEquals(0, fixture.stored().size)
        compose.onNodeWithText("120.00").performScrollTo().assertIsDisplayed()
        var beforeAcceptance: Bundle? = null
        compose.runOnIdle { beforeAcceptance = requireNotNull(editorStateOwner).save() }
        compose.onNodeWithText("保存").performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 && editor.value?.state?.value?.session == null }
        val original = fixture.stored().single()
        assertEquals(0, fixture.network.calls.size)
        assertEquals("income-ledger", original["ledgerId"])
        // This case requires no confirmed GET after the lost acknowledgement.
        // Block reads before dispatch so the save-triggered refresh cannot
        // legitimately reconcile the original before the offline reopen.
        fixture.network.failReads = true
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        assertEquals(1, fixture.network.results.size)
        reopenInOctober(original, requireNotNull(beforeAcceptance))
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

    private fun reopenInOctober(original: Map<String, String?>, preAckState: Bundle) {
        stopModels()
        // Restore a system snapshot taken before local acceptance; Room already owns the original.
        editorSavedState = preAckState
        fixture.advanceToOctober()
        fixture.network.failReads = true
        installModels()
        compose.waitUntil(10_000) { model.value?.state?.value?.loadState == IncomePlanLoadState.Failed &&
            model.value?.state?.value?.pendingSubmissions?.size == 1 }
        assertEquals(null, editor.value?.state?.value?.session)
        val reopened = fixture.stored().single()
        for (key in listOf("payload", "expectedRowVersion", "idempotencyKey", "ownerKey", "ledgerId")) {
            assertEquals(original[key], reopened[key])
        }
    }

    private fun installModels() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            model.value = IncomePlanViewModel(graph.incomePlanRepository)
            creator.value = IncomePlanCreateViewModel(graph.incomePlanRepository)
            val owner = IncomeDraftStateOwner(editorSavedState).also { editorStateOwner = it }
            val extras = MutableCreationExtras().apply {
                set(SAVED_STATE_REGISTRY_OWNER_KEY, owner)
                set(VIEW_MODEL_STORE_OWNER_KEY, owner)
            }
            editor.value = ViewModelProvider(owner.viewModelStore,
                incomePlanEditViewModelFactory(graph.incomePlanRepository, onDataChanged = { model.value?.refresh() }),
                extras)["income-plan-edit", IncomePlanEditViewModel::class.java]
        }
    }

    private fun stopModels() = compose.runOnIdle {
        model.value?.viewModelScope?.cancel()
        creator.value?.viewModelScope?.cancel()
        editorStateOwner?.let {
            editorSavedState = it.save()
            it.viewModelStore.clear()
        }
    }
}

/** Exercises the production SavedStateHandle factory with Android's registry save/restore. */
internal class IncomeDraftStateOwner(restored: Bundle?) : SavedStateRegistryOwner, ViewModelStoreOwner {
    override val lifecycle = LifecycleRegistry(this)
    override val viewModelStore = ViewModelStore()
    private val controller = SavedStateRegistryController.create(this)
    override val savedStateRegistry = controller.savedStateRegistry

    init {
        controller.performAttach()
        controller.performRestore(restored)
        enableSavedStateHandles()
        lifecycle.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
    }

    fun save(): Bundle = Bundle().also(controller::performSave)
}
