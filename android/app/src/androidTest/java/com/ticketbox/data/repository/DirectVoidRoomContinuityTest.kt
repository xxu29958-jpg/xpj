package com.ticketbox.data.repository

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtVoidCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentVoidCreateRequestDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.ui.screens.DebtDetailScreen
import com.ticketbox.ui.screens.settings.syncStatusOverview
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtAction
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.DebtActivityViewModel
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import com.ticketbox.viewmodel.OutboxRecoveryRepositories
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.outboxStatusViewModelFactory
import java.io.IOException
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.flow.first
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/** Real detail Save, dispatcher, disk Room and Global recovery share the original command. */
class DirectVoidRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val remote = DirectVoidRoomProbe()
    private val fixture = DebtAdjustmentConnectedFixture(context, remote.service)
    private val detail = mutableStateOf<DebtDetailViewModel?>(null)
    private lateinit var proposals: MemberRepaymentProposalViewModel
    private lateinit var history: DebtActivityViewModel

    @After fun close() { stopDetail(); fixture.close() }

    @Test fun committedDebtVoidLostAckSurvivesRoomReopenDespiteTerminalDebt() {
        assertOriginalSurvivesReopen(DebtAction.Void)
    }

    @Test fun committedRepaymentVoidLostAckSurvivesRoomReopenDespiteRestoredBalance() {
        assertOriginalSurvivesReopen(DebtAction.RepaymentVoid)
    }

    @Test fun debtVoidRetryAfterGraphReopenKeepsOriginalKeyBodyAndOcc() {
        assertOriginalReplay(DebtAction.Void)
    }

    @Test fun repaymentVoidRetryAfterGraphReopenKeepsOriginalReceiptTargetKeyBodyAndOcc() {
        assertOriginalReplay(DebtAction.RepaymentVoid)
    }

    private fun assertOriginalSurvivesReopen(action: DebtAction) {
        showDetail()
        saveFromForm(action)
        val original = fixture.stored().single()
        assertEquals(0, remote.calls.size)
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        assertEquals(1, remote.facts.size)
        assertEquals("原记录重复", remote.calls.single().reason)
        assertEquals(2L, remote.calls.single().expectedRowVersion)
        assertEquals(if (action == DebtAction.Void) "voided" else "open", remote.current.status)
        assertEquals(if (action == DebtAction.Void) 0L else 50_000L, remote.current.remainingAmountCents)
        stopDetail()
        installDetail()
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.rowVersion == 3L }
        val pending = requireNotNull(detail.value).state.value.pendingWrites
        assertEquals("The original committed-but-unacknowledged void must remain recoverable", 1, pending.size)
        assertTrue(pending.single().isUnresolved)
        assertFalse(requireNotNull(detail.value).state.value.canWriteActions)
        assertEquals(remote.calls.single().key, original["idempotencyKey"])
        assertEquals("2", original["expectedRowVersion"])
        assertTrue(requireNotNull(original["payload"]).contains("原记录重复"))
        if (action == DebtAction.RepaymentVoid) assertTrue(requireNotNull(original["payload"]).contains(remote.payment.publicId))
        compose.onNodeWithText("重试原提交").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
        assertOriginalColumns(original)
        remote.loseResponse = false
        remote.failReads = true
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { detail.value?.state?.value?.pendingWrites?.singleOrNull()?.row?.receiptJson != null }
        compose.onNodeWithText(context.getString(R.string.debt_void_confirmed)).performScrollTo().assertIsDisplayed()
        assertNotNull(fixture.stored().single()["receiptJson"])
        assertOriginalColumns(original)
        assertEquals(remote.calls.first(), remote.calls.last())
        assertEquals(1, remote.facts.size)
    }

    private fun assertOriginalReplay(action: DebtAction) = runBlocking {
        val firstGraph = fixture.reopen()
        val binding = requireNotNull(firstGraph.debtWriteRepository.currentAccess()).binding
        submit(firstGraph.debtWriteRepository, binding, action).getOrThrow()
        val original = fixture.stored().single()
        assertEquals(1, fixture.drain(maxAttempts = 1).failures)
        assertEquals(1, remote.facts.size)
        val reopenedGraph = fixture.reopen()
        val pending = reopenedGraph.debtWriteRepository.observeWrites(binding, remote.current.publicId)
            .first().single()
        reopenedGraph.debtWriteRepository.recover(binding, pending, drop = false).getOrThrow()
        remote.loseResponse = false
        // The original ACK remains its first snapshot even after another legitimate change.
        val receipt = remote.current
        remote.current = remote.current.copy(rowVersion = 4, remainingAmountCents = 1234)
        assertEquals(1, fixture.drain().done)
        assertEquals(remote.calls.first(), remote.calls.last())
        assertEquals("Recovery must reuse the original key rather than write another correction",
            remote.calls.first().key, remote.calls.last().key)
        assertEquals(1, remote.facts.size)
        assertEquals(receipt, requireNotNull(com.ticketbox.OutboxAdapterGraph().debtVoidReceiptAdapter
            .fromJson(requireNotNull(fixture.stored().single()["receiptJson"]))))
        assertOriginalColumns(original)
    }

    @Test fun globalRecoveryRefreshesAllFiveExistingConsumersAfterOriginalRepaymentVoidAck() {
        remote.current = remote.current.copy(direction = "owed_to_me")
        remote.syncCanonical()
        val graph = fixture.reopen()
        lateinit var consumers: RetainedAdjustmentConsumers
        lateinit var sync: OutboxStatusViewModel
        compose.runOnIdle { consumers = RetainedAdjustmentConsumers(graph); sync = globalSync() }
        try {
            compose.waitUntil(10_000) { consumers.balances() == List(5) { 40_000L } }
            val binding = requireNotNull(graph.debtWriteRepository.currentAccess()).binding
            runBlocking { submit(graph.debtWriteRepository, binding, DebtAction.RepaymentVoid).getOrThrow() }
            val original = fixture.stored().single()
            assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
            compose.waitUntil(10_000) { sync.uiState.value.status.failed.size == 1 }
            compose.runOnIdle { sync.retry(sync.uiState.value.status.failed.single()) }
            compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
            remote.loseResponse = false
            assertEquals(1, runBlocking { fixture.drain() }.done)
            compose.waitUntil(10_000) { consumers.balances() == List(5) { 50_000L } }
            assertEquals(remote.calls.first(), remote.calls.last())
            assertEquals(1, remote.facts.size)
            assertOriginalColumns(original)
        } finally { compose.runOnIdle { consumers.close(); sync.viewModelScope.cancel() } }
    }

    @Test fun legacyAcceptedVoidRequiresReviewInDetailAndGlobalAndOnlyLocalStopPreservesOriginal() {
        showDetail()
        saveFromForm(DebtAction.RepaymentVoid)
        val original = fixture.stored().single()
        remote.legacyAccepted = true
        assertEquals(1, runBlocking { fixture.drain() }.failures)
        compose.waitUntil(10_000) { detail.value?.state?.value?.pendingWrites?.singleOrNull()?.requiresReview == true }
        compose.onNodeWithText(context.getString(R.string.debt_void_original_requires_review)).performScrollTo().assertExists()
        val pending = requireNotNull(detail.value).state.value.pendingWrites.single()
        assertFalse(pending.canRetry)
        assertTrue(runBlocking { fixture.graph.debtWriteRepository.recover(requireNotNull(detail.value).state.value.binding!!,
            pending, drop = false) }.isFailure)
        lateinit var sync: OutboxStatusViewModel
        compose.runOnIdle { sync = globalSync() }
        try {
            compose.waitUntil(10_000) { sync.uiState.value.status.failed.size == 1 }
            val failed = sync.uiState.value.status.failed.single()
            assertFalse(sync.uiState.value.offersRetry(failed))
            compose.runOnIdle { sync.retry(failed) }
            compose.waitUntil(10_000) { sync.uiState.value.message != null }
            assertOriginalColumns(original)
            assertEquals(1, remote.calls.size)
            compose.runOnIdle { sync.dropFailed(failed) }
            compose.waitUntil(10_000) { fixture.stored().single()["status"] == "abandoned" }
            compose.waitUntil(10_000) {
                detail.value?.state?.value?.pendingWrites?.singleOrNull()?.row?.status == PendingMutationStatus.Abandoned &&
                    sync.uiState.value.debtWrites.values.singleOrNull()?.row?.status == PendingMutationStatus.Abandoned &&
                    sync.uiState.value.status.failed.isEmpty()
            }
            compose.onNodeWithText("原作废已被接受", substring = true).performScrollTo().assertIsDisplayed()
            compose.onNodeWithText("原记录重复").assertExists()
            compose.onNodeWithText(context.getString(R.string.debt_void_original_repayment, remote.payment.publicId)).assertExists()
            compose.onNodeWithText(context.getString(R.string.debt_void_review_title)).assertDoesNotExist()
            compose.onNodeWithText(context.getString(R.string.debt_void_original_requires_review)).assertDoesNotExist()
            compose.onNodeWithText(context.getString(R.string.debt_write_stopped_body)).assertDoesNotExist()
            compose.onNodeWithText(context.getString(R.string.debt_write_retry)).assertDoesNotExist()
            val stoppedIntent = requireNotNull(detail.value).state.value.pendingWrites.single()
            assertFalse(stoppedIntent.requiresReview)
            assertFalse(stoppedIntent.canRetry)
            val state = sync.uiState.value
            val overview = syncStatusOverview(state.status, emptyList(), state.debtWrites.values.toList())
            assertEquals(0, overview.reviewRequiredCount)
            assertEquals(0, overview.needsActionCount)
            assertEquals(1, overview.stoppedCount)
            assertEquals(DEBT_VOID_ORIGINAL_REQUIRES_REVIEW, stoppedIntent.row.lastError)
            assertOriginalColumns(original)
            assertEquals(1, remote.facts.size)
            assertEquals(0, runBlocking { fixture.drain() }.attempted)
        } finally { compose.runOnIdle { sync.viewModelScope.cancel() } }
    }

    @Test fun debtVoidFromPreviousSessionStaysReadableButCannotResumeWithNewCurrentBinding() {
        assertChangedOriginCannotResume(DebtAction.Void, changeSession = true)
    }

    @Test fun repaymentVoidFromPreviousBindingRevisionStaysReadableButCannotResumeWithNewCurrentBinding() {
        assertChangedOriginCannotResume(DebtAction.RepaymentVoid, changeSession = false)
    }

    private fun assertChangedOriginCannotResume(action: DebtAction, changeSession: Boolean) {
        showDetail()
        saveFromForm(action)
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        val original = fixture.stored().single()
        stopDetail()
        fixture.session = if (changeSession) fixture.session.copy(sessionGeneration = "new-session")
            else fixture.session.copy(bindingRevision = "new-binding-revision")
        installDetail()
        compose.waitUntil(10_000) { detail.value?.state?.value?.pendingWrites?.singleOrNull() != null }
        val state = requireNotNull(detail.value).state.value
        val binding = requireNotNull(state.binding)
        val pending = state.pendingWrites.single()
        assertNotNull(pending.intent)
        compose.onNodeWithText("原记录重复").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.debt_write_retry)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.debt_write_original_binding_changed)).assertExists()
        assertFalse(pending.canRetry)
        assertTrue(runBlocking { fixture.graph.debtWriteRepository.recover(binding, pending, drop = false) }.isFailure)
        assertEquals(0, runBlocking { fixture.drain() }.attempted)
        assertEquals(original, fixture.stored().single())
        assertEquals(1, remote.calls.size)
        assertEquals(1, remote.facts.size)
        lateinit var sync: OutboxStatusViewModel
        compose.runOnIdle { sync = globalSync() }
        try {
            compose.waitUntil(10_000) { sync.uiState.value.status.failed.size == 1 }
            val failed = sync.uiState.value.status.failed.single()
            assertFalse(sync.uiState.value.offersRetry(failed))
            compose.runOnIdle { sync.retry(failed) }
            compose.waitUntil(10_000) { sync.uiState.value.message != null }
            assertEquals(original, fixture.stored().single())
            assertEquals(1, remote.calls.size)
            compose.runOnIdle { sync.dropFailed(failed) }
            compose.waitUntil(10_000) { fixture.stored().single()["status"] == "abandoned" }
            assertOriginalColumns(original)
            assertEquals(0, runBlocking { fixture.drain() }.attempted)
        } finally { compose.runOnIdle { sync.viewModelScope.cancel() } }
    }

    @Test fun foreignBindingCannotAdoptRoomOriginalOrStopIt() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.debtWriteRepository.currentAccess()).binding
        submit(graph.debtWriteRepository, binding, DebtAction.RepaymentVoid).getOrThrow()
        assertEquals(1, fixture.drain(maxAttempts = 1).failures)
        val pending = graph.debtWriteRepository.observeWrites(binding, remote.current.publicId).first().single()
        val original = fixture.stored().single()
        fixture.session = fixture.session.copy(sessionGeneration = "foreign-session", identity = fixture.session.identity.copy(
            devicePublicId = "40000000-0000-4000-8000-000000000009"))
        val reopened = fixture.reopen()
        assertTrue(reopened.debtWriteRepository.observeWrites(binding, remote.current.publicId).first().isEmpty())
        assertTrue(reopened.debtWriteRepository.recover(binding, pending, drop = false).isFailure)
        assertTrue(reopened.debtWriteRepository.recover(binding, pending, drop = true).isFailure)
        assertEquals(0, fixture.drain().attempted)
        assertEquals(original, fixture.stored().single())
        assertEquals(1, remote.calls.size)
        assertEquals(1, remote.facts.size)
    }

    @Test fun readonlyGlobalRecoveryKeepsOriginalAndAllowsOnlyLocalStop() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.debtWriteRepository.currentAccess()).binding
        submit(graph.debtWriteRepository, binding, DebtAction.RepaymentVoid).getOrThrow()
        assertEquals(1, fixture.drain(maxAttempts = 1).failures)
        val original = fixture.stored().single()
        fixture.session = fixture.session.copy(identity = fixture.session.identity.copy(role = "viewer"))
        fixture.reopen()
        lateinit var sync: OutboxStatusViewModel
        compose.runOnIdle { sync = globalSync() }
        try {
            compose.waitUntil(10_000) { sync.uiState.value.status.failed.size == 1 && sync.uiState.value.bindingReady }
            val row = sync.uiState.value.status.failed.single()
            assertFalse(sync.uiState.value.offersRetry(row))
            compose.runOnIdle { sync.retry(row) }
            compose.waitUntil(10_000) { sync.uiState.value.message != null }
            assertEquals(original, fixture.stored().single())
            assertEquals(1, remote.calls.size)
            compose.runOnIdle { sync.dropFailed(row) }
            compose.waitUntil(10_000) { fixture.stored().single()["status"] == "abandoned" }
            assertOriginalColumns(original)
            assertEquals(1, remote.facts.size)
            assertEquals(0, fixture.drain().attempted)
        } finally { compose.runOnIdle { sync.viewModelScope.cancel() } }
    }

    private suspend fun submit(writes: DebtWriteActions, binding: LogicalSessionBinding, action: DebtAction) = when (action) {
        DebtAction.Void -> writes.saveVoid(binding, remote.current.toDomain(), "  原记录重复  ")
        DebtAction.RepaymentVoid -> writes.saveRepaymentVoid(binding, remote.current.toDomain(), remote.payment.publicId, "  原记录重复  ")
        else -> error("Only the two direct void owners are in scope")
    }

    private fun saveFromForm(action: DebtAction) {
        compose.waitUntil(10_000) { detail.value?.state?.value?.canWriteActions == true }
        compose.runOnIdle { requireNotNull(detail.value).openAction(action,
            remote.payment.takeIf { action == DebtAction.RepaymentVoid }) }
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("  原记录重复  ")
        compose.onNodeWithText("保存").performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 && detail.value?.state?.value?.activeAction == null }
    }

    private fun assertOriginalColumns(original: Map<String, String?>) {
        for (field in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "serverUrl", "createdAt")) {
            assertEquals(original[field], fixture.stored().single()[field])
        }
    }

    private fun showDetail() {
        installDetail()
        compose.setContent { detail.value?.let { model ->
            TicketboxTheme(skin = AppSkin.Paper) { DebtDetailScreen(model, proposals, history, {}) }
        } }
    }

    private fun installDetail() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            proposals = MemberRepaymentProposalViewModel(graph.debtRepository.proposals)
            history = DebtActivityViewModel(graph.debtRepository.activity)
            detail.value = DebtDetailViewModel(graph.debtRepository, graph.debtWriteRepository)
                .also { it.loadDebt(remote.current.publicId) }
        }
    }

    private fun globalSync() = outboxStatusViewModelFactory(fixture.outbox, fixture.graph.expenseRepository,
        OutboxRecoveryRepositories(fixture.graph.debtCreationRepository, fixture.graph.recurringRepository.occurrences,
            fixture.graph.incomePlanRepository, fixture.graph.debtWriteRepository, fixture.graph.goalEditRepository,
            fixture.graph.budgetRepository, fixture.graph.recurringRepository, fixture.graph.ruleRepository, repaymentReviews = fixture.graph.repaymentReviewRepository))
        .create(OutboxStatusViewModel::class.java)

    private fun stopDetail() = compose.runOnIdle {
        detail.value?.viewModelScope?.cancel()
        if (::proposals.isInitialized) proposals.viewModelScope.cancel()
        if (::history.isInitialized) history.viewModelScope.cancel()
    }
}

private data class OriginalVoidRoomCall(
    val debtPublicId: String, val repaymentPublicId: String?, val reason: String,
    val expectedRowVersion: Long, val key: String,
)

/** Mirrors claim-before-OCC and immutable original result; it is not a second server owner. */
private class DirectVoidRoomProbe {
    private val baseline = DebtAdjustmentConnectedNetwork()
    var current = baseline.current.copy(remainingAmountCents = 40_000, paidAmountCents = 10_000)
    val payment = DebtRepayment("repayment-original", 10_000, current.createdAt, current.createdAt, "active")
    var loseResponse = true
    var failReads = false
    var legacyAccepted = false
    init { syncCanonical() }
    fun syncCanonical() { baseline.current = current; baseline.failReads = failReads }
    val calls = mutableListOf<OriginalVoidRoomCall>()
    val facts = mutableMapOf<String, Pair<OriginalVoidRoomCall, DebtDto>>()
    val service = object : ApiService by baseline.service {
        override suspend fun debt(publicId: String): DebtDto {
            check(publicId == current.publicId)
            if (failReads) throw IOException("Synthetic canonical read failure")
            return current
        }

        override suspend fun voidDebt(publicId: String, request: DebtVoidCreateRequestDto,
            idempotencyKey: String?): DebtDto = commit(OriginalVoidRoomCall(publicId, null, request.reason,
            request.expectedRowVersion, requireNotNull(idempotencyKey)))

        override suspend fun voidDebtRepayment(publicId: String, request: RepaymentVoidCreateRequestDto,
            idempotencyKey: String?): DebtDto = commit(OriginalVoidRoomCall(publicId, request.repaymentPublicId,
            request.reason, request.expectedRowVersion, requireNotNull(idempotencyKey)))
    }

    private fun commit(call: OriginalVoidRoomCall): DebtDto {
        calls += call
        check(call.debtPublicId == current.publicId)
        facts[call.key]?.let { (original, receipt) ->
            check(original == call)
            return receipt
        }
        if (call.expectedRowVersion != current.rowVersion) {
            throw HttpException(Response.error<DebtDto>(409,
                """{"error":"state_conflict","message":"原记录已变化"}""".toResponseBody("application/json".toMediaType())))
        }
        check(call.repaymentPublicId == null || call.repaymentPublicId == payment.publicId)
        current = if (call.repaymentPublicId == null) {
            current.copy(status = "voided", remainingAmountCents = 0, rowVersion = current.rowVersion + 1)
        } else {
            current.copy(status = "open", remainingAmountCents = 50_000, paidAmountCents = 0,
                rowVersion = current.rowVersion + 1)
        }
        facts[call.key] = call to current
        syncCanonical()
        if (legacyAccepted) throw HttpException(Response.error<DebtDto>(409,
            """{"error":"debt_void_original_requires_review","message":"原作废已被接受，请核对原记录"}"""
                .toResponseBody("application/json".toMediaType())))
        if (loseResponse) throw IOException("Synthetic response loss after the original void committed")
        return current
    }
}
