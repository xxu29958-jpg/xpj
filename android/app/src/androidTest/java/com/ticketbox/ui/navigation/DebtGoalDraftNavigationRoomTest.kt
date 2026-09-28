package com.ticketbox.ui.navigation

import android.content.Context
import android.os.Bundle
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.text.AnnotatedString
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.SAVED_STATE_REGISTRY_OWNER_KEY
import androidx.lifecycle.VIEW_MODEL_STORE_OWNER_KEY
import androidx.lifecycle.viewmodel.MutableCreationExtras
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.repository.DebtAdjustmentConnectedNetwork
import com.ticketbox.data.repository.GoalEditActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.IncomeDraftStateOwner
import com.ticketbox.data.repository.createDebtGoal
import com.ticketbox.data.repository.originalCreation
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.screens.CreateDebtGoalScreen
import com.ticketbox.viewmodel.CreateDebtGoalViewModel
import com.ticketbox.viewmodel.createDebtGoalViewModelFactory
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.CompletableDeferred
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class DebtGoalDraftNavigationRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val originalDebt = DebtAdjustmentConnectedNetwork().current.copy(ledgerId = "correction-ledger")
    private var debtAvailable = true
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?) =
                GoalListResponseDto(emptyList())
            override suspend fun debts(lens: String?) = DebtListResponseDto(
                if (debtAvailable) listOf(originalDebt) else emptyList(), "CNY")
        }
    }
    private val mounted = mutableStateOf(true)
    private val draftModel = mutableStateOf<CreateDebtGoalViewModel?>(null)
    private var draftOwner: IncomeDraftStateOwner? = null
    private lateinit var outer: NavHostController
    private lateinit var inner: NavHostController

    @After fun close() {
        try {
            compose.runOnIdle { mounted.value = false; draftOwner?.viewModelStore?.clear(); harness.models.viewModelStore.clear() }
            compose.waitForIdle()
        } finally { harness.close() }
    }

    @Test fun actualPopAndReentryKeepRawNameAndUnavailableSelectionUntilTheUserResolvesThem() {
        showRoutes()
        enterGoals()
        compose.onNodeWithText(context.getString(R.string.debt_goal_create_cta)).performClick()
        val originalOwner = creationOwner()
        compose.waitUntil(10_000) { originalOwner.state.value.editable && originalOwner.state.value.candidates.size == 1 }
        compose.onNode(hasSetTextAction()).performScrollTo().performTextReplacement("  原还债任务  ")
        closeSoftKeyboard()
        compose.waitForIdle()
        compose.onNodeWithText(requireNotNull(originalDebt.counterpartyLabel)).performScrollTo().performClick()
        val originalKey = originalOwner.state.value.creationKey
        assertEquals(setOf(originalDebt.publicId), originalOwner.state.value.selectedDebtIds)
        val entry = compose.runOnIdle { requireNotNull(inner.currentBackStackEntry) }
        compose.runOnIdle { assertTrue(inner.popBackStack()); debtAvailable = false }
        compose.waitUntil(10_000) { entry.lifecycle.currentState == Lifecycle.State.DESTROYED }

        enterGoals()
        assertNotSame(entry, compose.runOnIdle { inner.currentBackStackEntry })
        assertSame(originalOwner, creationOwner())
        compose.onNodeWithText(context.getString(R.string.goal_draft_continue)).performClick()
        compose.waitUntil(10_000) { !originalOwner.state.value.isLoadingDebts && originalOwner.state.value.candidates.isEmpty() }
        compose.onNode(hasSetTextAction()).assertTextEquals("  原还债任务  ")
        assertEquals(originalKey, originalOwner.state.value.creationKey)
        assertEquals(setOf(originalDebt.publicId), originalOwner.state.value.unavailableSelectedDebtIds)
        compose.onNodeWithText(context.getString(R.string.debt_goal_create_save)).assertIsNotEnabled()
        assertTrue(harness.fixture.stored().isEmpty())
        compose.onNodeWithText(context.getString(R.string.debt_goal_create_remove_unavailable)).performScrollTo().performClick()
        assertTrue(originalOwner.state.value.selectedDebtIds.isEmpty())
        compose.onNode(hasSetTextAction()).assertTextEquals("  原还债任务  ")

        compose.onNodeWithText(context.getString(R.string.goal_draft_discard)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        compose.onNode(hasSetTextAction()).assertTextEquals("  原还债任务  ")
        compose.runOnIdle { debtAvailable = true }
        compose.onNodeWithText(context.getString(R.string.goal_draft_discard)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.goal_draft_discard_confirm)).performClick()
        compose.waitUntil(10_000) { originalOwner.state.value.editable && originalOwner.state.value.candidates.size == 1 }
        assertEquals("", compose.onNode(hasSetTextAction()).fetchSemanticsNode().config[SemanticsProperties.EditableText].text)
        assertNotEquals(originalKey, originalOwner.state.value.creationKey)
        compose.onNode(hasSetTextAction()).performScrollTo().performTextReplacement("新的还债安排")
        closeSoftKeyboard()
        compose.waitForIdle()
        compose.onNodeWithText(requireNotNull(originalDebt.counterpartyLabel)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.debt_goal_create_save)).assertIsEnabled()
        assertTrue(harness.fixture.stored().isEmpty())
    }

    private fun creationOwner(): CreateDebtGoalViewModel = compose.runOnIdle {
        ViewModelProvider(outer.getBackStackEntry(MAIN_ROUTE), createDebtGoalViewModelFactory(
            harness.screenFactory.goalEditRepository, harness.screenFactory.debtRepository, harness.screenFactory.debtWriteRepository))[
            CreateDebtGoalViewModelKey, CreateDebtGoalViewModel::class.java]
    }

    @Test fun globalOriginalRouteReopensTheExactDebtCommandWithoutAMonetaryFormOrNewWrite() = runBlocking {
        val actions = harness.screenFactory.goalEditRepository
        val binding = requireNotNull(actions.currentAccess()).binding
        val id = actions.createDebtGoal(binding, "原清偿提交", listOf(originalDebt.publicId), "retained-debt-task").getOrThrow()
        harness.fixture.outbox.markFailed(id, "client_upgrade_required")
        val original = requireNotNull(actions.originalCreation(binding, "retained-debt-task").getOrThrow())
        val stored = harness.fixture.stored()
        showRoutes()
        compose.runOnIdle { inner.navigate(goalCreationRoute(original)) }
        compose.waitForIdle()
        val model = creationOwner()
        compose.waitUntil(10_000) { model.state.value.pending?.row?.id == id }
        compose.onNodeWithText(context.getString(R.string.debt_goal_create_title)).assertIsDisplayed()
        compose.onNode(SemanticsMatcher.expectValue(SemanticsProperties.EditableText, AnnotatedString("原清偿提交")))
            .assertIsNotEnabled()
        compose.onNodeWithText(context.getString(R.string.budget_month_next)).assertDoesNotExist()
        assertEquals(setOf(originalDebt.publicId), model.state.value.selectedDebtIds)
        assertEquals("retained-debt-task", model.state.value.creationKey)
        assertEquals(stored, harness.fixture.stored())
        assertTrue(model.state.value.createdPublicId == null)
    }

    @Test fun registrySnapshotBeforeAcceptanceRejoinsItsRoomOriginalWithoutRebuildingTheSelection() {
        val localAck = CompletableDeferred<Unit>()
        val repository = harness.screenFactory.goalEditRepository
        val actions = object : GoalEditActions by repository {
            override suspend fun create(binding: LogicalSessionBinding, request: GoalCreateRequestDto, creationKey: String): Result<Long> {
                val result = repository.create(binding, request, creationKey)
                if (result.isSuccess) localAck.await()
                return result
            }
        }
        installDraft(actions, null)
        compose.setContent { if (mounted.value) TicketboxTheme(skin = AppSkin.Paper) {
            draftModel.value?.let { CreateDebtGoalScreen(it, {}, { error("Local acceptance is not server confirmation") }) }
        } }
        try {
            val original = requireNotNull(draftModel.value)
            compose.waitUntil(10_000) { original.state.value.editable && original.state.value.candidates.size == 1 }
            compose.onNode(hasSetTextAction()).performScrollTo().performTextReplacement("  保存前的原稿  ")
            closeSoftKeyboard()
            compose.waitForIdle()
            compose.onNodeWithText(requireNotNull(originalDebt.counterpartyLabel)).performScrollTo().performClick()
            val snapshot = compose.runOnIdle { requireNotNull(draftOwner).save() }
            val key = original.state.value.creationKey
            compose.onNode(hasSetTextAction()).performScrollTo().performTextReplacement("实际接受的原任务")
            closeSoftKeyboard()
            compose.waitForIdle()
            compose.onNodeWithText(context.getString(R.string.debt_goal_create_save)).performClick()
            compose.waitUntil(10_000) { harness.fixture.stored().size == 1 }
            val accepted = harness.fixture.stored().single()
            compose.runOnIdle { draftOwner?.viewModelStore?.clear(); draftModel.value = null; debtAvailable = false }
            harness.reopen()
            installDraft(harness.screenFactory.goalEditRepository, snapshot)
            val restored = requireNotNull(draftModel.value)
            compose.waitUntil(10_000) { restored.state.value.pending?.row?.id?.toString() == accepted["id"] }
            assertEquals(key, restored.state.value.creationKey)
            assertEquals("实际接受的原任务", restored.state.value.name)
            assertEquals(setOf(originalDebt.publicId), restored.state.value.selectedDebtIds)
            compose.onNode(SemanticsMatcher.expectValue(SemanticsProperties.EditableText, AnnotatedString("实际接受的原任务")))
                .assertIsNotEnabled()
            assertEquals(listOf(accepted), harness.fixture.stored())
            assertTrue(restored.state.value.createdPublicId == null)
        } finally { localAck.complete(Unit) }
    }

    private fun installDraft(actions: GoalEditActions, saved: Bundle?) = compose.runOnIdle {
        val owner = IncomeDraftStateOwner(saved).also { draftOwner = it }
        val extras = MutableCreationExtras().apply {
            set(SAVED_STATE_REGISTRY_OWNER_KEY, owner)
            set(VIEW_MODEL_STORE_OWNER_KEY, owner)
        }
        draftModel.value = ViewModelProvider(owner.viewModelStore, createDebtGoalViewModelFactory(actions,
            harness.screenFactory.debtRepository, harness.screenFactory.debtWriteRepository), extras)[
            CreateDebtGoalViewModelKey, CreateDebtGoalViewModel::class.java]
    }

    private fun enterGoals() {
        compose.runOnIdle { inner.navigate(ProductSecondaryPage.DebtGoals.route) }
        compose.waitForIdle()
    }

    private fun showRoutes() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    outer = rememberNavController()
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) {
                            inner = rememberNavController()
                            NavHost(inner, startDestination = PrimaryDomain.Plans.route) {
                                composable(PrimaryDomain.Plans.route) { }
                                addObligationRoutes(MainProductRouteDependencies(
                                    MainNavigationRuntime(outer, harness.shell, harness.screenFactory), inner,
                                    MainWorkspaceControls(SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System,
                                        CurrencyCode.CNY, onThemeModeChange = {}, onCurrencyChange = {}),
                                        onBindingCleared = { error("Navigation preserves the identity") }),
                                ))
                            }
                        }
                    }
                }
            }
        }
        compose.waitForIdle()
    }
}
