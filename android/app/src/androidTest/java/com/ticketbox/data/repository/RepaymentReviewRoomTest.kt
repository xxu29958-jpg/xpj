package com.ticketbox.data.repository

import androidx.test.core.app.ApplicationProvider
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDismissRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import com.ticketbox.domain.model.Debt
import java.io.IOException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.cancel
import androidx.lifecycle.viewModelScope
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Disk Room and production graph/Outbox; response loss is injected only at the transport boundary. */
class RepaymentReviewRoomTest {
    private val capture = RepaymentDraftDto("review-original", "alipay", null, "JPY", "原采集", "2026-09-01T00:00:00Z",
        "pending", createdAt = "2026-09-01T00:00:01Z", originalCurrencyCode = "CNY", originalAmountMinor = 10000)
    private var loseReply = true
    private var refuseDismiss = false
    private val accepted = mutableSetOf<String>()
    private val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext()) { api ->
        object : ApiService by api {
            override suspend fun repaymentDraft(publicId: String): RepaymentDraftDto {
                assertEquals(capture.publicId, publicId)
                return capture
            }
            override suspend fun confirmRepaymentDraft(publicId: String, request: RepaymentDraftConfirmRequestDto, idempotencyKey: String?): RepaymentDraftDto {
                assertEquals(capture.publicId, publicId)
                assertEquals("90.00", request.originalAmount)
                assertEquals(7L, request.expectedRowVersion)
                accepted += requireNotNull(idempotencyKey)
                if (loseReply) throw IOException("isolated lost reply")
                return capture.copy(status = "confirmed", committedDebtPublicId = request.targetDebtPublicId, committedRepaymentPublicId = "original-repayment")
            }
            override suspend fun dismissRepaymentDraft(publicId: String, request: RepaymentDraftDismissRequestDto): RepaymentDraftDto {
                assertEquals(capture.publicId, publicId)
                if (refuseDismiss) throw retrofit2.HttpException(retrofit2.Response.error<Any>(403,
                    okhttp3.ResponseBody.create(null, """{"error":"permission_denied"}""")))
                return capture.copy(status = "dismissed")
            }
        }
    }
    @After fun close() = fixture.close()

    @Test fun rawInputAndOriginalReceiptSurviveReopenAndQueryCleanup() = runBlocking {
        var graph = fixture.reopen()
        var binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        graph.repaymentReviewRepository.open(binding, capture.toDomain()).getOrThrow()
        graph.repaymentReviewRepository.select(binding, capture.publicId, debt(binding)).getOrThrow()
        graph.repaymentReviewRepository.money(binding, capture.publicId, "CNY", " 90.").getOrThrow()
        val raw = graph.repaymentReviewRepository.observe(binding, capture.publicId).first()
        graph = fixture.reopen()
        graph.expenseRepository.clearLocalCache()
        assertEquals(raw, graph.repaymentReviewRepository.observe(binding, capture.publicId).first())
        fixture.renewBinding()
        binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        val oldIdentity = graph.repaymentReviewRepository.observe(binding, capture.publicId).first()
        assertTrue(oldIdentity.bindingChanged)
        assertEquals(" 90.", oldIdentity.input?.amountText)
        assertTrue(graph.repaymentReviewRepository.money(binding, capture.publicId, "CNY", "50.00").isFailure)
        graph.repaymentReviewRepository.reviewAgain(binding, capture.publicId).getOrThrow()
        val reopened = graph.repaymentReviewRepository.observe(binding, capture.publicId).first()
        assertEquals(" 90.", reopened.input?.amountText)
        assertEquals(null, reopened.input?.debtPublicId)
        assertTrue(reopened.input?.originalKey != raw.input?.originalKey)
        graph.repaymentReviewRepository.select(binding, capture.publicId, debt(binding)).getOrThrow()
        graph.repaymentReviewRepository.money(binding, capture.publicId, "CNY", "90.00").getOrThrow()
        val id = graph.repaymentReviewRepository.submit(binding, capture.toDomain(), false).getOrThrow()
        val original = fixture.stored().single()
        drain()
        assertEquals("pending", fixture.stored().single()["status"])
        graph = fixture.reopen()
        assertTrue(graph.repaymentReviewRepository.money(binding, capture.publicId, "CNY", "50.00").isFailure)
        assertEquals(id, graph.repaymentReviewRepository.submit(binding, capture.toDomain(), false).getOrThrow())
        loseReply = false
        drain()
        val completed = fixture.stored().single()
        assertEquals("done", completed["status"])
        assertEquals(original["payload"], completed["payload"])
        assertEquals(original["idempotencyKey"], completed["idempotencyKey"])
        assertEquals(1, accepted.size)
        graph = fixture.reopen()
        val receipt = graph.repaymentReviewRepository.observe(binding, capture.publicId).first().original
        assertTrue(requireNotNull(receipt?.receiptJson).contains("original-repayment"))
        fixture.switchLedger()
        assertTrue(graph.repaymentReviewRepository.submit(binding, capture.toDomain(), false).isFailure)
    }

    @Test fun dismissalKeepsOneOriginalAcrossReopenWithoutCreatingADebtPayment() = runBlocking {
        var graph = fixture.reopen()
        val binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        graph.repaymentReviewRepository.open(binding, capture.toDomain()).getOrThrow()
        val id = graph.repaymentReviewRepository.submit(binding, capture.toDomain(), true).getOrThrow()
        graph = fixture.reopen()
        assertEquals(id, graph.repaymentReviewRepository.submit(binding, capture.toDomain(), true).getOrThrow())
        drain()
        assertEquals("done", fixture.stored().single()["status"])
        assertTrue(accepted.isEmpty())
        assertTrue(requireNotNull(graph.repaymentReviewRepository.observe(binding, capture.publicId).first().original?.receiptJson).contains("dismissed"))
    }

    @Test fun globalSyncStopRetainsTheRejectedOriginalAndInput() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        graph.repaymentReviewRepository.open(binding, capture.toDomain()).getOrThrow()
        graph.repaymentReviewRepository.submit(binding, capture.toDomain(), true).getOrThrow()
        val original = fixture.stored().single()
        refuseDismiss = true
        drain()
        val model = withContext(Dispatchers.Main) {
            com.ticketbox.viewmodel.OutboxStatusViewModel(fixture.outbox, graph.expenseRepository,
                com.ticketbox.viewmodel.OutboxRecoveryRepositories(graph.debtCreationRepository, graph.recurringRepository.occurrences,
                    graph.incomePlanRepository, graph.debtWriteRepository, graph.goalEditRepository, graph.budgetRepository,
                    graph.recurringRepository, graph.ruleRepository, graph.repaymentReviewRepository))
        }
        try {
            val state = withTimeout(5000) { model.uiState.first { it.bindingReady && it.status.failed.size == 1 } }
            withContext(Dispatchers.Main) { model.dropFailed(state.status.failed.single()) }
            val stopped = withTimeout(5000) { graph.repaymentReviewRepository.observe(binding, capture.publicId).first {
                it.original?.status == com.ticketbox.data.local.PendingMutationStatus.Abandoned
            } }
            assertEquals(original["payload"], stopped.original?.payloadJson)
            assertEquals(original["idempotencyKey"], stopped.input?.originalKey)
            assertEquals(1, fixture.stored().size)
        } finally { withContext(Dispatchers.Main) { model.viewModelScope.cancel() } }
    }

    private suspend fun drain() {
        val adapters = OutboxAdapterGraph()
        val guard = LedgerRequestGuard(fixture.apiProvider)
        OutboxDrainEngine(fixture.outbox, listOf(
            ConfirmRepaymentDraftDispatcher(guard, adapters.repaymentReviewAdapter, adapters.repaymentDraftReceiptAdapter),
            DismissRepaymentDraftDispatcher(guard, adapters.repaymentDismissAdapter, adapters.repaymentDraftReceiptAdapter),
        ), now = fixture.clock::millis).drainOnce()
    }

    private fun debt(binding: LogicalSessionBinding) = Debt(publicId = "original-debt", ledgerId = binding.ledgerId,
        direction = "i_owe", counterpartyType = "external", counterpartyAccountId = null, counterpartyLabel = "原欠款",
        principalAmountCents = 10000, remainingAmountCents = 10000, paidAmountCents = 0, status = "open", sourceType = "manual",
        sourceId = null, homeCurrencyCode = "JPY", originalCurrencyCode = "JPY", originalAmountMinor = 10000,
        createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 7)
}
