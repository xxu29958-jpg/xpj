package com.ticketbox.ui.navigation

import android.content.Context
import android.os.Bundle
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onLast
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.SemanticsMatcher
import com.ticketbox.ui.assertEditableTextEquals
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
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
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.DebtRepaymentEvaluationDto
import com.ticketbox.data.remote.dto.DebtGoalLinkViewDto
import com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.ReplaceGoalDebtLinksDispatcher
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.viewmodel.DebtGoalLinksViewModel
import com.ticketbox.viewmodel.debtGoalLinksViewModelFactory
import androidx.test.platform.app.InstrumentationRegistry
import java.io.IOException
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
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
import com.ticketbox.ui.screens.DebtGoalLinksScreen
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
    private val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight") AppSkin.Midnight else AppSkin.Paper
    private val originalDebt = DebtAdjustmentConnectedNetwork().current.copy(ledgerId = "correction-ledger")
    private var debtAvailable = true
    private var showGoal = false
    private val anotherDebt = originalDebt.copy(publicId = "other-debt", counterpartyLabel = "另一笔欠款")
    private var loseLinkReply = false
    private var denyGoalRead = false
    private val linkRequests = mutableListOf<Pair<String?, DebtGoalLinksReplaceRequestDto>>()
    private val linkReceipts = mutableMapOf<String, GoalDto>()
    private lateinit var linksApi: ApiService
    private var existingGoal = GoalDto("debt-goal", "correction-ledger", "年底还清", "debt_repayment", "unbounded", null,
        null, null, null, null, null, "unavailable", "active", "2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z", 4, null,
        debtRepayment = DebtRepaymentEvaluationDto(1, "in_progress", false, linkedDebts = listOf(
            DebtGoalLinkViewDto(originalDebt.publicId, "open", "i_owe", "external", "家人甲", 90000, 90000, "CNY")),
            voidedDebtPublicIds = emptyList()))
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?) =
                GoalListResponseDto(if (showGoal) listOf(existingGoal) else emptyList())
            override suspend fun goal(publicId: String, timezone: String?): GoalDto {
                if (denyGoalRead) throw HttpException(Response.error<Any>(403, "{}".toResponseBody()))
                return existingGoal
            }
            override suspend fun debts(lens: String?) = DebtListResponseDto(
                if (debtAvailable) if (showGoal) listOf(originalDebt, anotherDebt) else listOf(originalDebt) else emptyList(), "CNY")
            override suspend fun replaceGoalDebtLinks(publicId: String, request: DebtGoalLinksReplaceRequestDto,
                idempotencyKey: String?, timezone: String?): GoalDto {
                linkRequests += idempotencyKey to request
                val receipt = linkReceipts.getOrPut(requireNotNull(idempotencyKey)) {
                    check(publicId == existingGoal.publicId)
                    if (request.expectedRowVersion != existingGoal.rowVersion) throw HttpException(Response.error<Any>(409,
                        """{"error":"state_conflict","message":"目标已更新"}""".toResponseBody()))
                    existingGoal.copy(rowVersion = request.expectedRowVersion + 1,
                        debtRepayment = existingGoal.debtRepayment?.copy(linkedDebts = request.debtPublicIds.map { id ->
                            val debt = listOf(originalDebt, anotherDebt).single { it.publicId == id }
                            DebtGoalLinkViewDto(id, debt.status, debt.direction, debt.counterpartyType, debt.counterpartyLabel,
                                debt.principalAmountCents, debt.remainingAmountCents, debt.homeCurrencyCode)
                        })).also { existingGoal = it }
                }
                if (loseLinkReply) throw IOException("Reply lost after the association was committed")
                return receipt
            }
        }.also { linksApi = it }
    }
    private val mounted = mutableStateOf(true)
    private val draftModel = mutableStateOf<CreateDebtGoalViewModel?>(null)
    private val linksModel = mutableStateOf<DebtGoalLinksViewModel?>(null)
    private var draftOwner: IncomeDraftStateOwner? = null
    private lateinit var outer: NavHostController
    private lateinit var inner: NavHostController

    @After fun close() {
        try {
            compose.runOnIdle { mounted.value = false; draftOwner?.viewModelStore?.clear(); harness.models.viewModelStore.clear() }
            compose.waitForIdle()
        } finally { harness.close() }
    }

    @Test fun associationTaskRetainsSelectionAndReopensTheSameRoomCommandFromSyncAfterLostReply() {
        if (InstrumentationRegistry.getArguments().getString("captureLong") == "true") {
            existingGoal = existingGoal.copy(name = "年底还清家人垫付的旅行费用与朋友借款，继续保留每一笔原始偿还记录")
        }
        showGoal = true
        showRoutes()
        enterGoals()
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(existingGoal.name))
        capture("debt-goal-list")
        compose.onNodeWithText(existingGoal.name).performClick()
        compose.onNodeWithText("家人甲").performScrollTo()
        capture("debt-goal-detail")
        compose.onNodeWithText("调整关联").performScrollTo().performClick()
        compose.onNodeWithText("这个目标关联哪些欠款").assertIsDisplayed()
        capture("debt-goal-links")
        val owner = linksOwner()
        compose.onNodeWithText("另一笔欠款").performScrollTo().performClick()
        val selection = owner.state.value.selectedLabels
        assertEquals(setOf(originalDebt.publicId, anotherDebt.publicId), selection.keys)
        androidx.test.espresso.Espresso.pressBack()
        compose.runOnIdle { assertTrue(inner.popBackStack()) }
        enterGoals()
        compose.onNodeWithText(context.getString(R.string.debt_goal_links_continue)).performScrollTo().performClick()
        assertSame(owner, linksOwner())
        compose.waitUntil(10_000) { owner.state.value.canSave }
        assertEquals(selection, owner.state.value.selectedLabels)
        harness.fixture.role("viewer")
        compose.waitUntil(10_000) { !owner.state.value.canModify }
        compose.onNodeWithText(context.getString(R.string.debt_goal_links_save)).assertIsNotEnabled()
        assertEquals(selection, owner.state.value.selectedLabels)
        assertTrue(runBlocking { harness.fixture.stored().isEmpty() })
        capture("debt-goal-links-readonly")
        harness.fixture.role("member")
        compose.waitUntil(10_000) { owner.state.value.canSave }
        compose.onNodeWithText(context.getString(R.string.debt_goal_links_save)).performClick()
        compose.waitUntil(10_000) { owner.state.value.pending != null && !owner.state.value.isSaving }
        assertTrue(linkRequests.isEmpty())
        val original = runBlocking { harness.fixture.stored().single() }
        assertEquals("4", original["expectedRowVersion"])
        capture("debt-goal-links-pending")
        loseLinkReply = true
        assertEquals(1, runBlocking { linkEngine().drainOnce().failures })
        compose.waitUntil(10_000) { owner.state.value.pending?.canRetry == true }
        val stored = runBlocking { harness.fixture.stored().single() }
        existingGoal = existingGoal.copy(rowVersion = 6, name = "另一个端后来更新的名称")
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        harness.reopen()
        compose.runOnIdle { mounted.value = true }
        compose.waitForIdle()
        compose.runOnIdle { inner.navigate(ProductSecondaryPage.ObligationSync.route) }
        compose.waitUntil(10_000) { compose.onAllNodesWithText(context.getString(R.string.goal_submission_open))
            .fetchSemanticsNodes().isNotEmpty() }
        capture("debt-goal-links-sync")
        compose.onNodeWithText(context.getString(R.string.goal_submission_open)).performScrollTo().performClick()
        val reopened = linksOwner()
        compose.waitUntil(10_000) { reopened.state.value.pending?.canRetry == true }
        assertNotSame(owner, reopened)
        assertEquals(selection, reopened.state.value.selectedLabels)
        assertEquals(stored, runBlocking { harness.fixture.stored().single() })
        capture("debt-goal-links-original")
        loseLinkReply = false
        compose.onNodeWithText(context.getString(R.string.spending_goal_submission_retry)).performScrollTo().performClick()
        compose.waitUntil(10_000) { reopened.state.value.pending?.canRetry == false && !reopened.state.value.isSaving }
        assertEquals(1, runBlocking { linkEngine().drainOnce().done })
        compose.waitUntil(10_000) { reopened.state.value.pending?.confirmed != null && reopened.state.value.canSave }
        assertEquals(5L, reopened.state.value.pending?.confirmed?.rowVersion)
        assertEquals(6L, reopened.state.value.goal?.rowVersion)
        assertEquals(listOf(original["idempotencyKey"], original["idempotencyKey"]), linkRequests.map { it.first })
        assertEquals(listOf(4L, 4L), linkRequests.map { it.second.expectedRowVersion })
        assertEquals(listOf(selection.keys.toList(), selection.keys.toList()), linkRequests.map { it.second.debtPublicIds })
        val done = runBlocking { harness.fixture.stored().single() }
        for (field in listOf("payload", "expectedRowVersion", "idempotencyKey", "ledgerId", "ownerKey", "serverUrl")) {
            assertEquals(field, original[field], done[field])
        }
        capture("debt-goal-links-confirmed")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("另一笔欠款"))
        compose.onNodeWithText("另一笔欠款").performClick()
        capture("debt-goal-links-continue-edit")
        assertEquals(setOf(originalDebt.publicId), reopened.state.value.selectedLabels.keys)
        assertEquals(5L, reopened.state.value.pending?.confirmed?.rowVersion)
        assertEquals(2, linkRequests.size)
    }

    @Test fun restoredSelectionSurvivesReadRevocationAndConflictReviewWaitsForExplicitSave() {
        showGoal = true
        installLinks(null)
        compose.setContent { if (mounted.value) TicketboxTheme(skin = skin) {
            linksModel.value?.let { DebtGoalLinksScreen(it, existingGoal.publicId, {}) }
        } }
        val original = requireNotNull(linksModel.value)
        compose.waitUntil(10_000) { original.state.value.canSave }
        compose.onNodeWithText(requireNotNull(originalDebt.counterpartyLabel)).performScrollTo().performClick()
        compose.onNodeWithText("另一笔欠款").performScrollTo().performClick()
        val selected = original.state.value.selectedLabels
        val snapshot = compose.runOnIdle { requireNotNull(draftOwner).save() }
        compose.runOnIdle { draftOwner?.viewModelStore?.clear(); linksModel.value = null }
        existingGoal = existingGoal.copy(rowVersion = 5, name = "另一个端更新的目标")
        installLinks(snapshot)
        val restored = requireNotNull(linksModel.value)
        compose.waitUntil(10_000) { restored.state.value.canSave }
        assertNotSame(original, restored)
        assertEquals(selected, restored.state.value.selectedLabels)
        denyGoalRead = true
        compose.runOnIdle { restored.refresh() }
        compose.waitUntil(10_000) { !restored.state.value.isLoading }
        assertTrue(restored.state.value.goal == null && restored.state.value.candidates.isEmpty())
        assertEquals(selected, restored.state.value.selectedLabels)
        compose.onNodeWithText(context.getString(R.string.debt_goal_links_save)).assertIsNotEnabled()
        capture("debt-goal-links-withdrawn")
        denyGoalRead = false
        compose.runOnIdle { restored.refresh() }
        compose.waitUntil(10_000) { restored.state.value.canSave }
        compose.onNodeWithText(context.getString(R.string.debt_goal_links_save)).performClick()
        compose.waitUntil(10_000) { restored.state.value.pending != null && !restored.state.value.isSaving }
        val rejected = runBlocking { harness.fixture.stored().single() }
        assertEquals("4", rejected["expectedRowVersion"])
        runBlocking { linkEngine().drainOnce() }
        compose.waitUntil(10_000) { restored.state.value.pending?.row?.status == com.ticketbox.data.local.PendingMutationStatus.Conflict }
        capture("debt-goal-links-conflict")
        val review = context.getString(R.string.debt_goal_links_review)
        compose.onNodeWithText(review).performScrollTo().performClick()
        compose.onAllNodesWithText(review).onLast().performClick()
        compose.waitUntil(10_000) { restored.state.value.canSave && restored.state.value.pending == null }
        assertEquals(selected, restored.state.value.selectedLabels)
        assertTrue(runBlocking { harness.fixture.stored().isEmpty() })
        assertEquals(1, linkRequests.size)
        assertTrue(linkReceipts.isEmpty())
        capture("debt-goal-links-reviewed")
        compose.onNodeWithText(context.getString(R.string.debt_goal_links_save)).performClick()
        compose.waitUntil(10_000) { restored.state.value.pending != null && !restored.state.value.isSaving }
        val replacement = runBlocking { harness.fixture.stored().single() }
        assertEquals("5", replacement["expectedRowVersion"])
        assertNotEquals(rejected["idempotencyKey"], replacement["idempotencyKey"])
        assertEquals(1, runBlocking { linkEngine().drainOnce().done })
        compose.waitUntil(10_000) { restored.state.value.pending?.confirmed != null }
        assertEquals(6L, restored.state.value.pending?.confirmed?.rowVersion)
        assertEquals(selected.keys.toList(), linkRequests.last().second.debtPublicIds)
        assertEquals(1, linkReceipts.size)
        capture("debt-goal-links-review-confirmed")
    }

    private fun installLinks(saved: Bundle?) = compose.runOnIdle {
        val owner = IncomeDraftStateOwner(saved).also { draftOwner = it }
        val extras = MutableCreationExtras().apply {
            set(SAVED_STATE_REGISTRY_OWNER_KEY, owner)
            set(VIEW_MODEL_STORE_OWNER_KEY, owner)
        }
        linksModel.value = ViewModelProvider(owner.viewModelStore, debtGoalLinksViewModelFactory(
            harness.screenFactory.reportsRepository, harness.screenFactory.goalEditRepository,
            harness.screenFactory.debtRepository), extras)["debt-goal-links", DebtGoalLinksViewModel::class.java]
    }

    private fun linksOwner(): DebtGoalLinksViewModel = compose.runOnIdle {
        ViewModelProvider(outer.getBackStackEntry(MAIN_ROUTE), debtGoalLinksViewModelFactory(
            harness.screenFactory.reportsRepository, harness.screenFactory.goalEditRepository, harness.screenFactory.debtRepository))[
            "debt-goal-links", DebtGoalLinksViewModel::class.java]
    }

    private fun linkEngine(): OutboxDrainEngine {
        val adapters = OutboxAdapterGraph()
        return OutboxDrainEngine(harness.fixture.outbox, listOf(ReplaceGoalDebtLinksDispatcher({ linksApi },
            adapters.goalDebtLinksAdapter, adapters.goalReceiptAdapter,
            harness.fixture.graph.reportsRepository::invalidateGoalReadsAfterDelivery)), now = harness.fixture.clock::millis,
            maxAttempts = 1)
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        com.ticketbox.ui.saveConsumerArtPreview(name, compose.onRoot().captureToImage().asAndroidBitmap())
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
        compose.onNode(hasSetTextAction()).assertEditableTextEquals("  原还债任务  ")
        assertEquals(originalKey, originalOwner.state.value.creationKey)
        assertEquals(setOf(originalDebt.publicId), originalOwner.state.value.unavailableSelectedDebtIds)
        compose.onNodeWithText(context.getString(R.string.debt_goal_create_save)).assertIsNotEnabled()
        assertTrue(harness.fixture.stored().isEmpty())
        compose.onNodeWithText(context.getString(R.string.debt_goal_create_remove_unavailable)).performScrollTo().performClick()
        assertTrue(originalOwner.state.value.selectedDebtIds.isEmpty())
        compose.onNode(hasSetTextAction()).assertEditableTextEquals("  原还债任务  ")

        compose.onNodeWithText(context.getString(R.string.goal_draft_discard)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        compose.onNode(hasSetTextAction()).assertEditableTextEquals("  原还债任务  ")
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
                TicketboxTheme(skin = skin) {
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
