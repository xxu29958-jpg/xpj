package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.NotificationDraftRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import com.ticketbox.domain.model.RepaymentDraftSource
import com.ticketbox.domain.model.RepaymentNotificationDraft
import com.ticketbox.notification.PaymentNotificationResult
import java.io.IOException
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class NotificationCaptureRepositoryTest {
    @Test fun offlineNotificationKeepsItsOriginalCaptureForRecovery() = runTest {
        val f = CaptureFixture()
        val original = f.binding
        f.accept().getOrThrow()
        assertEquals(1, f.dao.rows.size)
        assertEquals(listOf(1), f.scheduledDepths)
        assertEquals(0, f.api.calls)
        val saved = f.dao.rows.values.single()
        assertEquals(original.ownerKey, saved.ownerKey)
        assertEquals("same-delivery", saved.idempotencyKey)
        f.dao.runnableBatches += listOf(saved.id)
        f.engine().drainOnce()
        assertEquals(PendingMutationStatus.Pending.wireValue, f.dao.rows.values.single().status)
        assertEquals(saved.payload, f.dao.rows.values.single().payload)
        assertEquals(0, f.published.size)
        val captured = requireNotNull(NotificationCaptureWire.payload.fromJson(saved.payload))
        assertEquals("2026-09-29 23:59", captured.timeEvidence?.fragments?.single()?.literal)
        assertEquals("Asia/Shanghai", captured.timeEvidence?.sourceTimezone)
        assertEquals("2026-09-30T08:00:00Z", captured.capturedAt)
        assertEquals("商户：星巴克", captured.fieldEvidence?.fragments?.single()?.literal)
    }

    @Test fun concurrentRedeliveryAndRepositoryRecreationKeepOneOriginalWhileNewPostRemainsSeparate() = runTest {
        val f = CaptureFixture()
        val ids = (1..8).map { async { f.accept().getOrThrow() } }.awaitAll()
        assertEquals(1, ids.distinct().size)
        val reopened = NotificationCaptureRepository(f.provider, f.newOutbox())
        assertEquals(ids.first(), reopened.accept(f.expense, f.binding, "same-delivery").getOrThrow())
        reopened.accept(f.expense, f.binding, "new-post-time").getOrThrow()
        assertEquals(2, f.dao.rows.size)
        assertEquals(0, f.api.calls)
    }

    @Test fun responseLossReplaysOriginalKeysForBothKindsBeforePublishingReceipt() = runTest {
        val f = CaptureFixture()
        f.api.offline = false
        f.api.loseReply = true
        f.accept().getOrThrow()
        f.repository.accept(f.repayment, f.binding, "repayment-delivery").getOrThrow()
        // A pre-upgrade Room original has neither parser metadata nor candidates.
        // It must use the same unified identity endpoint without rewriting that intent.
        val legacy = f.dao.rows.values.first()
        val oldPayload = requireNotNull(NotificationCaptureWire.payload.fromJson(legacy.payload)).copy(
            revision = 1, parserVersion = "legacy", candidates = emptyList(), timeEvidence = null, fieldEvidence = null)
        f.dao.rows[legacy.id] = legacy.copy(payload = NotificationCaptureWire.payload.toJson(oldPayload)
            .replace(",\"parserVersion\":\"legacy\"", "").replace(",\"candidates\":[]", ""))
        f.dao.runnableBatches += f.dao.rows.keys.toList()
        f.engine().drainOnce()
        assertEquals(2, f.api.accepted.size)
        assertEquals(2, f.dao.rows.values.count { it.status == "pending" })
        val originals = f.dao.rows.values.associate { it.id to (it.payload to it.idempotencyKey) }
        f.api.loseReply = false
        val later = Clock.offset(f.clock, java.time.Duration.ofHours(1))
        val reopened = f.newOutbox(later)
        f.dao.runnableBatches += f.dao.rows.keys.toList()
        f.engine(reopened, later).drainOnce()
        assertEquals(2, f.api.accepted.size)
        assertEquals(originals, f.dao.rows.values.associate { it.id to (it.payload to it.idempotencyKey) })
        assertEquals(2, f.dao.rows.values.count { it.status == "done" && it.receiptJson != null })
        assertEquals(listOf("expense:pending", "repayment:pending"), f.published)
        assertEquals(setOf("expense", "repayment"), f.api.requests.map { it.suggestedKind }.toSet())
        assertTrue(f.api.requests.all { it.originalCurrency == "CNY" && it.originalAmountMinor == 2680L })
    }

    @Test fun switchingPrincipalBeforeAcceptanceOrDrainNeverSendsIntoTheNewOwner() = runTest {
        val f = CaptureFixture()
        val original = f.binding
        f.accept().getOrThrow()
        f.session.rebindAsDifferentAccountForFixture("另一个人", "owner", "另一本", "另一台", "other-token")
        assertTrue(f.repository.accept(f.repayment, original, "old-post").isFailure)
        f.engine().drainOnce()
        assertTrue(f.dao.batchCalls.first().ownerKey != original.ownerKey)
        assertEquals(1, f.dao.rows.size)
        assertEquals(0, f.api.calls)
        assertEquals(original.ownerKey, f.dao.rows.values.single().ownerKey)
    }

    @Test fun changedContentCannotReplaceAnAlreadyAcceptedNotification() = runTest {
        val f = CaptureFixture()
        f.accept().getOrThrow()
        val original = f.dao.rows.values.single().payload
        val changed = PaymentNotificationResult.Expense(f.expense.draft.copy(amountCents = 5000))
        assertTrue(f.repository.accept(changed, f.binding, "same-delivery").isFailure)
        assertEquals(original, f.dao.rows.values.single().payload)
        assertEquals(1, f.dao.rows.size)
    }

    @Test fun oneSystemDeliveryCannotBecomeBothAnExpenseAndARepayment() = runTest {
        val f = CaptureFixture()
        f.accept().getOrThrow()
        assertTrue(f.repository.accept(f.repayment, f.binding, "same-delivery").isFailure,
            "A changed interpretation must preserve the first original instead of creating a second financial task")
        assertEquals(1, f.dao.rows.size)
    }

    @Test fun acceptanceFailureDoesNotScheduleOrSend() = runTest {
        val f = CaptureFixture()
        f.dao.beforeInsert = { throw IllegalStateException("storage unavailable") }
        assertTrue(f.accept().isFailure)
        assertTrue(f.scheduledDepths.isEmpty())
        assertEquals(0, f.api.calls)
    }

    @Test fun aRefusedCaptureRetainsItsOriginalAndExplicitRetryDoesNotAllocateAnother() = runTest {
        val f = CaptureFixture()
        f.api.offline = false
        f.api.refusal = 403
        val id = f.repository.accept(f.repayment, f.binding, "repayment-refused").getOrThrow()
        val original = f.dao.rows.values.single()
        f.dao.runnableBatches += listOf(id)
        f.engine().drainOnce()
        assertEquals("failed", f.dao.rows.values.single().status)
        assertTrue(f.published.isEmpty())
        assertTrue(f.api.accepted.isEmpty())
        f.api.refusal = null
        assertTrue(f.outbox.resolveFailed(id, FailedResolution.Retry()))
        f.dao.runnableBatches += listOf(id)
        f.engine().drainOnce()
        val completed = f.dao.rows.values.single()
        assertEquals("done", completed.status)
        assertEquals(original.payload, completed.payload)
        assertEquals(original.idempotencyKey, completed.idempotencyKey)
        assertEquals(listOf("repayment:pending"), f.published)
    }
}

private class CaptureFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-session") }
    val api = CaptureResponseProbe()
    val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, session)
    val binding get() = assertNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val dao = FakePendingMutationDao()
    val clock: Clock = Clock.fixed(Instant.parse("2026-09-30T08:00:00Z"), ZoneOffset.UTC)
    val scheduledDepths = mutableListOf<Int>()
    val published = mutableListOf<String>()
    val outbox = newOutbox()
    val repository = NotificationCaptureRepository(provider, outbox)
    val expense = PaymentNotificationResult.Expense(NotificationDraft(NotificationDraftSource.WeChat, 2680, "星巴克", "餐饮", "2026-09-30T08:00:00Z"),
        timeEvidence = com.ticketbox.notification.NotificationTimeEvidence("Asia/Shanghai", listOf(
            com.ticketbox.notification.NotificationTimeFragment("text", "2026-09-29 23:59", "支付时间")), false),
        fieldEvidence = com.ticketbox.notification.NotificationFieldEvidence(listOf(
            com.ticketbox.notification.NotificationFieldFragment("text", "商户：星巴克"))))
    val repayment = PaymentNotificationResult.Repayment(RepaymentNotificationDraft(RepaymentDraftSource.Alipay, 2680, "花呗", "2026-09-30T08:00:00Z"))
    suspend fun accept() = repository.accept(expense, binding, "same-delivery")
    fun newOutbox(at: Clock = clock) = OutboxRepository(dao, at, onRowsDeleted = {},
        bindingProvider = { provider.currentSession().toOutboxBinding() }, onEnqueued = { scheduledDepths += dao.rows.size })
    fun engine(queue: OutboxRepository = outbox, at: Clock = clock) = OutboxDrainEngine(queue,
        listOf(NotificationCaptureDispatcher(LedgerRequestGuard(provider),
            { _, result -> published += "expense:${result.status}" }, { _, result -> published += "repayment:${result.status}" }, { _, _ -> published += "review" })), now = at::millis)
}

private class CaptureResponseProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    var calls = 0
    var offline = true
    var loseReply = false
    var refusal: Int? = null
    val accepted = linkedSetOf<String>()
    val requests = linkedSetOf<com.ticketbox.data.remote.dto.PaymentCaptureCreateDto>()
    private val expenseApi = FakeApiService(mutableListOf(), 0)
    override suspend fun capturePayment(request: com.ticketbox.data.remote.dto.PaymentCaptureCreateDto): com.ticketbox.data.remote.dto.PaymentCaptureDto {
        beforeRequest()
        accepted += request.notificationKey
        requests += request
        if (loseReply) throw IOException("reply lost after commit")
        return com.ticketbox.data.remote.dto.PaymentCaptureDto("capture-${request.notificationKey}", 1, request.source,
            request.capturedAt, request.originalCurrency, request.originalAmountMinor, request.merchant, request.suggestedKind,
            request.parserVersion, request.candidates, 12L.takeIf { request.suggestedKind == "expense" },
            "8f939f48-e646-4afb-b54f-7bb6b536d9ef".takeIf { request.suggestedKind == "expense" },
            "draft-original".takeIf { request.suggestedKind == "repayment" })
    }
    override suspend fun expense(id: Long): com.ticketbox.data.remote.dto.ExpenseDto {
        val original = requests.single { it.suggestedKind == "expense" }
        return expenseApi.createNotificationDraft(NotificationDraftRequestDto(source = original.source,
            originalCurrency = original.originalCurrency, originalAmount = java.math.BigDecimal.valueOf(requireNotNull(original.originalAmountMinor), 2).toPlainString(),
            merchant = original.merchant, category = null, expenseTime = original.capturedAt, notificationKey = original.notificationKey))
    }
    override suspend fun repaymentDraft(publicId: String): RepaymentDraftDto {
        val original = requests.single { it.suggestedKind == "repayment" }
        return RepaymentDraftDto(publicId, original.source, original.originalAmountMinor, "CNY", original.merchant,
            original.capturedAt, "pending", createdAt = original.capturedAt)
    }

    private fun beforeRequest() {
        calls++
        if (offline) throw IOException("offline")
        refusal?.let { throw HttpException(Response.error<Any>(it,
            """{"error":"permission_denied"}""".toResponseBody("application/json".toMediaType()))) }
    }
}
