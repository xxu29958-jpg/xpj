package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.RepaymentReviewInputEntity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import java.io.IOException
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class RepaymentReviewCommandTest {
    @Test fun unknownReplyReplaysTheOriginalMoneyDebtVersionAndKey() = runTest {
        val remote = ReviewReplyProbe()
        val session = TestSessionFixture().apply { saveToken("synthetic-session") }
        val provider = testApiServiceProvider(object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = remote
        }, session)
        val binding = assertNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
        val adapters = OutboxAdapterGraph()
        val input = reviewInput(binding)
        val intent = input.command(binding, remote.capture.toDomain(), false, adapters)
        val dao = FakePendingMutationDao()
        fun queue() = OutboxRepository(dao, onRowsDeleted = {}, bindingProvider = { provider.currentSession().toOutboxBinding() })
        fun engine(outbox: OutboxRepository) = OutboxDrainEngine(outbox, listOf(ConfirmRepaymentDraftDispatcher(
            LedgerRequestGuard(provider), adapters.repaymentReviewAdapter, adapters.repaymentDraftReceiptAdapter)))
        val outbox = queue()
        outbox.enqueue(LedgerRequestGuard(provider).bindExact(binding), intent)
        val original = dao.rows.values.single()
        engine(outbox).drainOnce()
        assertEquals("pending", dao.rows.values.single().status)
        remote.loseReply = false
        engine(queue()).drainOnce()
        val completed = dao.rows.values.single()
        assertEquals("done", completed.status)
        assertEquals(original.payload, completed.payload)
        assertEquals(original.idempotencyKey, completed.idempotencyKey)
        assertEquals(1, remote.accepted.size)
        assertEquals(listOf(7L, 7L), remote.calls.map { it.expectedRowVersion })
        assertTrue(remote.calls.all { it.originalCurrency == "CNY" && it.originalAmount == "90.00" })
        assertEquals(" 90.00 ", adapters.repaymentReviewAdapter.fromJson(completed.payload)?.reviewedAmount)
        assertEquals("repayment-original", adapters.repaymentDraftReceiptAdapter.fromJson(requireNotNull(completed.receiptJson))?.committedRepaymentPublicId)
    }

    @Test fun unchangedCapturedMoneyKeepsItsKnownHomeAmountWhileAnExplicitCorrectionTravelsSeparately() {
        val binding = LogicalSessionBinding("https://isolated.invalid", "ledger", "owner", "session", "binding")
        val adapters = OutboxAdapterGraph()
        val original = ReviewReplyProbe().capture.copy(amountCents = 1400L).toDomain()
        val input = reviewInput(binding)
        val unchanged = input.copy(amountText = "100.00").command(binding, original, false, adapters)
        val oldMoney = assertNotNull(adapters.repaymentReviewAdapter.fromJson(unchanged.payloadJson)).request
        assertEquals(null, oldMoney.originalCurrency)
        assertEquals(null, oldMoney.originalAmount)
        val changed = assertNotNull(adapters.repaymentReviewAdapter.fromJson(input.command(binding, original, false, adapters).payloadJson)).request
        assertEquals("90.00", changed.originalAmount)
        assertEquals(10000L, original.originalAmountMinor)
        assertEquals(1400L, original.amountCents)
    }
}

private fun reviewInput(binding: LogicalSessionBinding) = RepaymentReviewInputEntity(binding.ownerKey, binding.ledgerId,
    "capture-original", binding.serverUrl, binding.sessionGeneration, binding.bindingRevision, "original-review-key",
    "CNY", " 90.00 ", "debt-original", "原欠款", "USD", 7)

private class ReviewReplyProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    val capture = RepaymentDraftDto("capture-original", "alipay", null, "USD", "原银行卡", "2026-09-01T00:00:00Z",
        "pending", createdAt = "2026-09-01T00:00:01Z", originalCurrencyCode = "CNY", originalAmountMinor = 10000)
    var loseReply = true
    val accepted = mutableSetOf<String>()
    val calls = mutableListOf<RepaymentDraftConfirmRequestDto>()
    override suspend fun confirmRepaymentDraft(publicId: String, request: RepaymentDraftConfirmRequestDto, idempotencyKey: String?): RepaymentDraftDto {
        assertEquals(capture.publicId, publicId)
        accepted += requireNotNull(idempotencyKey)
        calls += request
        if (loseReply) throw IOException("reply lost after isolated acceptance")
        return capture.copy(status = "confirmed", committedDebtPublicId = request.targetDebtPublicId, committedRepaymentPublicId = "repayment-original")
    }
}
