package com.ticketbox.data.repository

import androidx.lifecycle.viewModelScope
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDismissRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import com.ticketbox.domain.model.Debt
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Disk Room and production graph/Outbox; response loss is injected only at the transport boundary. */
class RepaymentReviewRoomTest {
    private val capture = RepaymentDraftDto("review-original", "alipay", null, "JPY", "原采集", "2026-09-01T00:00:00Z",
        "pending", createdAt = "2026-09-01T00:00:01Z", originalCurrencyCode = "CNY", originalAmountMinor = 10000)
    private var loseCorrectionReply = true
    private val correctionCalls = mutableListOf<Pair<String, com.ticketbox.data.remote.dto.RepaymentAsExpenseDto>>()
    private var loseReply = true
    private var refuseReview = false
    private var sourceCorrection = false
    private var sourcePublications = 0
    private var expectedReviewDate: String? = null
    private val confirmCalls = mutableListOf<Pair<String, RepaymentDraftConfirmRequestDto>>()
    private val fixture: ExpenseCorrectionConnectedFixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext()) { api ->
        object : ApiService by api {
            override suspend fun repaymentDraft(publicId: String): RepaymentDraftDto {
                assertEquals(capture.publicId, publicId)
                return capture
            }
            override suspend fun confirmRepaymentDraft(publicId: String, request: RepaymentDraftConfirmRequestDto, idempotencyKey: String?): RepaymentDraftDto {
                confirmCalls += requireNotNull(idempotencyKey) to request
                assertEquals(capture.publicId, publicId)
                assertEquals("90.00", request.originalAmount)
                assertEquals(7L, request.expectedRowVersion)
                assertEquals(expectedReviewDate, request.timeInput?.userLocalDate)
                refuseReviewIfRequired()
                if (loseReply) throw IOException("isolated lost reply")
                return capture.copy(status = "confirmed", committedDebtPublicId = "original-debt", committedRepaymentPublicId = "original-repayment",
                    sourceExpensePublicId = if (sourceCorrection) fixture.network.current.publicId else null)
            }
            override suspend fun expenseFactBundle(id: String): com.ticketbox.data.remote.dto.ExpenseFactBundleDto {
                assertEquals(fixture.network.current.publicId, id)
                return api.expenseFactBundle(fixture.network.current.id.toString())
            }
            override suspend fun repaymentAsExpense(publicId: String, request: com.ticketbox.data.remote.dto.RepaymentAsExpenseDto,
                idempotencyKey: String): com.ticketbox.domain.model.PaymentCapture {
                assertEquals(capture.publicId, publicId)
                correctionCalls += idempotencyKey to request
                assertEquals(8L, request.correctionVersions?.debtRowVersion)
                assertEquals("原通知其实是消费", request.reason)
                if (loseCorrectionReply) throw IOException("lost correction reply")
                return com.ticketbox.domain.model.PaymentCapture("event-original", 3, "alipay", capture.capturedAt,
                    "CNY", 9000, "原采集", "expense", "legacy", emptyList(), fixture.network.current.id,
                    fixture.network.current.publicId, capture.publicId)
            }
            override suspend fun dismissRepaymentDraft(publicId: String, request: RepaymentDraftDismissRequestDto): RepaymentDraftDto {
                assertEquals(capture.publicId, publicId)
                refuseReviewIfRequired()
                return capture.copy(status = "dismissed")
            }
        }
    }
    @After fun close() = fixture.close()

    @Test fun defaultTargetStaysNonExplicitThroughReapplicationAndLostReply() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        graph.repaymentReviewRepository.open(binding, capture.toDomain(), debt(binding)).getOrThrow()
        graph.repaymentReviewRepository.edit(binding, capture.publicId,
            RepaymentReviewChange.TargetDebt(debt(binding), explicitlySelected = false)).getOrThrow()
        graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.Money("CNY", "90.00")).getOrThrow()
        assertEquals(false, graph.repaymentReviewRepository.observe(binding, capture.publicId).first().input?.targetChoiceExplicit)
        graph.repaymentReviewRepository.submit(binding, capture.toDomain(), false).getOrThrow()
        drain()
        assertEquals(null, confirmCalls.single().second.targetChoiceExplicit) // Omitted false preserves legacy replay bytes.
        fixture.reopen()
        loseReply = false
        drain()
        assertEquals(2, confirmCalls.size)
        assertEquals(confirmCalls[0], confirmCalls[1])
    }

    @Test fun rawInputAndOriginalReceiptSurviveReopenAndQueryCleanup() = runBlocking {
        expectedReviewDate = "2026-08-31"
        var graph = fixture.reopen()
        var binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        graph.repaymentReviewRepository.open(binding, capture.toDomain(), debt(binding)).getOrThrow()
        assertEquals(false, graph.repaymentReviewRepository.observe(binding, capture.publicId).first().input?.targetChoiceExplicit)
        graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.TargetDebt(debt(binding))).getOrThrow()
        graph.repaymentReviewRepository.edit(binding, capture.publicId,
            RepaymentReviewChange.TargetDebt(debt(binding), explicitlySelected = false)).getOrThrow()
        graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.Money("CNY", " 90.")).getOrThrow()
        graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.Date("2026-08-31")).getOrThrow()
        val raw = graph.repaymentReviewRepository.observe(binding, capture.publicId).first()
        assertEquals(true, raw.input?.targetChoiceExplicit)
        graph = fixture.reopen()
        graph.expenseRepository.clearLocalCache()
        assertEquals(raw, graph.repaymentReviewRepository.observe(binding, capture.publicId).first())
        fixture.renewBinding()
        binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        val oldIdentity = graph.repaymentReviewRepository.observe(binding, capture.publicId).first()
        assertTrue(oldIdentity.bindingChanged)
        assertEquals(" 90.", oldIdentity.input?.amountText)
        assertEquals("2026-08-31", oldIdentity.input?.paymentDate)
        assertEquals(3L, oldIdentity.input?.calendarRevision)
        assertTrue(graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.Money("CNY", "50.00")).isFailure)
        graph.repaymentReviewRepository.reviewAgain(binding, capture.publicId).getOrThrow()
        val reopened = graph.repaymentReviewRepository.observe(binding, capture.publicId).first()
        assertEquals(" 90.", reopened.input?.amountText)
        assertEquals("2026-08-31", reopened.input?.paymentDate)
        assertEquals(null, reopened.input?.debtPublicId)
        assertEquals(false, reopened.input?.targetChoiceExplicit)
        assertTrue(reopened.input?.originalKey != raw.input?.originalKey)
        graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.TargetDebt(debt(binding))).getOrThrow()
        graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.Money("CNY", "90.00")).getOrThrow()
        val id = graph.repaymentReviewRepository.submit(binding, capture.toDomain(), false).getOrThrow()
        val original = fixture.stored().single()
        drain()
        assertEquals(true, confirmCalls.last().second.targetChoiceExplicit)
        assertEquals("pending", fixture.stored().single()["status"])
        graph = fixture.reopen()
        assertTrue(graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.Money("CNY", "50.00")).isFailure)
        assertTrue(graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.Date("2026-09-15")).isFailure)
        assertEquals(id, graph.repaymentReviewRepository.submit(binding, capture.toDomain(), false).getOrThrow())
        loseReply = false
        sourceCorrection = true
        drain()
        assertEquals("pending", fixture.stored().single()["status"])
        graph = fixture.reopen()
        drain()
        val completed = fixture.stored().single()
        assertEquals("done", completed["status"])
        assertEquals(original["payload"], completed["payload"])
        assertEquals(original["idempotencyKey"], completed["idempotencyKey"])
        assertEquals(3, confirmCalls.size)
        assertEquals(2, sourcePublications)
        assertTrue(fixture.expenseDao.observeConfirmed(binding.ledgerId).first().any { it.publicId == fixture.network.current.publicId })
        assertEquals(confirmCalls.first(), confirmCalls.last())
        assertEquals(original["idempotencyKey"], confirmCalls.first().first)
        val sent = confirmCalls.first().second
        assertEquals("CNY", sent.originalCurrency)
        assertEquals("original-debt", sent.targetDebtPublicId)
        assertEquals(3L, sent.timeInput?.calendarRevision)
        assertEquals("date_only", sent.timeInput?.precision)
        assertEquals(null, sent.timeInput?.instantUtc)
        graph = fixture.reopen()
        val receipt = graph.repaymentReviewRepository.observe(binding, capture.publicId).first().original
        assertTrue(requireNotNull(receipt?.receiptJson).contains("original-repayment"))
        val confirmed = capture.copy(status = "confirmed", committedDebtPublicId = "original-debt",
            committedRepaymentPublicId = "original-repayment", correctionVersions =
                com.ticketbox.data.remote.dto.RepaymentCorrectionVersionsDto(8, 2, 1)).toDomain()
        graph.repaymentReviewRepository.correctAsExpense(binding, confirmed, "原通知其实是消费").getOrThrow()
        drain()
        val correctionOriginal = fixture.stored().last()
        assertEquals("pending", correctionOriginal["status"])
        graph = fixture.reopen()
        loseCorrectionReply = false
        drain()
        assertEquals("done", fixture.stored().last()["status"])
        assertEquals(correctionOriginal["payload"], fixture.stored().last()["payload"])
        assertEquals(correctionCalls.first(), correctionCalls.last())
        assertEquals(receipt?.receiptJson, graph.repaymentReviewRepository.observe(binding, capture.publicId).first().original?.receiptJson)
        fixture.switchLedger()
        assertTrue(graph.repaymentReviewRepository.correctAsExpense(binding, confirmed, "保留原身份").isFailure)
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
        assertTrue(confirmCalls.isEmpty())
        assertTrue(requireNotNull(graph.repaymentReviewRepository.observe(binding, capture.publicId).first().original?.receiptJson).contains("dismissed"))
    }

    @Test fun globalSyncStopRetainsTheRejectedOriginalAndInput() = runBlocking {
        for (dismiss in listOf(true, false)) stopRejectedOriginal(dismiss)
    }

    private suspend fun stopRejectedOriginal(dismiss: Boolean) {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        graph.repaymentReviewRepository.open(binding, capture.toDomain()).getOrThrow()
        if (!dismiss) {
            graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.TargetDebt(debt(binding))).getOrThrow()
            graph.repaymentReviewRepository.edit(binding, capture.publicId, RepaymentReviewChange.Money("CNY", "90.00")).getOrThrow()
        }
        graph.repaymentReviewRepository.submit(binding, capture.toDomain(), dismiss).getOrThrow()
        val original = fixture.stored().single()
        refuseReview = true
        drain()
        assertEquals("failed", fixture.stored().single()["status"])
        val model = withContext(Dispatchers.Main) {
            com.ticketbox.viewmodel.OutboxStatusViewModel(fixture.outbox, graph.expenseRepository,
                com.ticketbox.viewmodel.OutboxRecoveryRepositories(graph.debtCreationRepository, graph.recurringRepository.occurrences,
                    graph.incomePlanRepository, graph.debtWriteRepository, graph.goalEditRepository, graph.budgetRepository,
                    graph.recurringRepository, graph.ruleRepository, graph.repaymentReviewRepository))
        }
        try {
            val state = withTimeout(5000) { model.uiState.first { it.bindingReady && it.status.failed.size == 1 } }
            withContext(Dispatchers.Main) { model.dropFailed(state.status.failed.single()) }
            val recovery = withTimeout(5000) { model.uiState.first {
                it.status.failed.isEmpty() || it.message != null
            } }
            check(recovery.message == null) { "Global recovery refused the retained original: ${recovery.message}" }
            val stopped = withTimeout(5000) { graph.repaymentReviewRepository.observe(binding, capture.publicId).first {
                it.original?.status == com.ticketbox.data.local.PendingMutationStatus.Abandoned
            } }
            assertEquals(original["payload"], stopped.original?.payloadJson)
            assertEquals(original["idempotencyKey"], stopped.input?.originalKey)
            assertEquals(1, fixture.stored().size)
        } finally {
            withContext(Dispatchers.Main) { model.viewModelScope.cancel() }
            fixture.close()
        }
    }

    private fun refuseReviewIfRequired() {
        if (refuseReview) throw retrofit2.HttpException(retrofit2.Response.error<Any>(403,
            okhttp3.ResponseBody.create(null, """{"error":"permission_denied"}""")))
    }

    private suspend fun drain() {
        val adapters = OutboxAdapterGraph()
        val guard = LedgerRequestGuard(fixture.apiProvider)
        OutboxDrainEngine(fixture.outbox, listOf(
            ConfirmRepaymentDraftDispatcher(guard, adapters.debt.repaymentReviewAdapter, adapters.debt.repaymentDraftReceiptAdapter,
                { ledgerId, bundle ->
                    sourcePublications++
                    if (sourcePublications == 1) throw IOException("isolated cache publication failure")
                    val projection = bundle.toCacheProjection(ledgerId)
                    fixture.expenseDao.applyExpenseFactBundle(ledgerId, projection.root, projection.activeOffsets)
                }),
            DismissRepaymentDraftDispatcher(guard, adapters.debt.repaymentDismissAdapter, adapters.debt.repaymentDraftReceiptAdapter),
            PaymentCaptureResolutionDispatcher(guard) { _, _ -> },
        ), now = fixture.clock::millis).drainOnce()
    }

    private fun debt(binding: LogicalSessionBinding) = Debt(publicId = "original-debt", ledgerId = binding.ledgerId,
        direction = "i_owe", counterpartyType = "external", counterpartyAccountId = null, counterpartyLabel = "原欠款",
        principalAmountCents = 10000, remainingAmountCents = 10000, paidAmountCents = 0, status = "open", sourceType = "manual",
        sourceId = null, homeCurrencyCode = "JPY", originalCurrencyCode = "JPY", originalAmountMinor = 10000,
        createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 7,
        repaymentCalendar = com.ticketbox.domain.model.DebtRepaymentCalendar(3, "Pacific/Honolulu"))
}
