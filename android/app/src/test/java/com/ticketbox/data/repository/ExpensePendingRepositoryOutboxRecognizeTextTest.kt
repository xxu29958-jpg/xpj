package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

/** Original pasted text is admitted unchanged; recognition results belong to worker completion. */
internal class ExpensePendingRepositoryOutboxRecognizeTextTest : ExpensePendingRepositoryOutboxTestBase() {
    private val pastedText = "星巴克 拿铁 ¥35 2026-05-20"

    @Test
    fun `pasted text survives admission and a worker network failure with its original key`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val api = ApiServiceStub(extras = ApiServiceStubExtras(recognizeTextResult = ApiResult.Throw(IOException("offline"))))
        val repo = buildRepository(api, outbox)
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val accepted = repo.recognizeTextAllowingOffline(binding, baseline, pastedText).getOrThrow()
        val original = dao.rows.values.single()
        assertEquals(baseline, accepted.expense)
        assertEquals(listOf(original.id), accepted.rowIds)
        assertEquals(PendingMutationType.RecognizeText.wireValue, original.type)
        assertEquals(PendingMutationStatus.Pending.wireValue, original.status)
        assertEquals("expense:${baseline.id}", original.targetId)
        assertEquals(binding.ownerKey, original.ownerKey)
        assertEquals(binding.ledgerId, original.ledgerId)
        assertEquals(binding.serverUrl, original.serverUrl)
        assertEquals(baseline.rowVersion, original.expectedRowVersion)
        val adapter = moshi().adapter(ExpenseRecognizeTextRequestDto::class.java)
        val request = requireNotNull(adapter.fromJson(original.payload))
        assertEquals(pastedText, request.rawText)
        assertEquals(0L, request.expectedRowVersion)
        assertNotNull(original.idempotencyKey)
        assertNull(api.lastRecognizeTextRequest)
        assertNull(api.lastRecognizeTextIdempotencyKey)
        val dispatcher = RecognizeTextDispatcher(apiProvider = { api }, payloadAdapter = adapter,
            publishExpense = { _, _ -> error("An unavailable transport cannot publish recognition") })
        assertEquals(1, OutboxDrainEngine(outbox, listOf(dispatcher)).drainOnce().retryable)
        val retained = dao.rows.values.single()
        assertEquals(PendingMutationStatus.Pending.wireValue, retained.status)
        assertEquals(original.idempotencyKey, api.lastRecognizeTextIdempotencyKey)
        assertEquals(original.idempotencyKey, retained.idempotencyKey)
        assertEquals(original.payload, retained.payload)
        assertEquals(baseline.rowVersion, api.lastRecognizeTextRequest?.expectedRowVersion)
    }

    @Test
    fun `only accepted worker recognition publishes the parsed snapshot`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val parsed = successExpenseDto()
        val api = ApiServiceStub(extras = ApiServiceStubExtras(recognizeTextResult = ApiResult.Success(parsed)))
        val repo = buildRepository(api, outbox)
        val accepted = repo.recognizeTextAllowingOffline(requireNotNull(repo.captureDeferredLedgerBinding()), baseline, pastedText).getOrThrow()
        assertEquals(baseline, accepted.expense)
        assertNull(api.lastRecognizeTextRequest)
        val original = dao.rows.values.single()
        val published = mutableListOf<ExpenseDto>()
        val dispatcher = RecognizeTextDispatcher(apiProvider = { api },
            payloadAdapter = moshi().adapter(ExpenseRecognizeTextRequestDto::class.java),
            publishExpense = { _, expense -> published += expense })
        assertEquals(1, OutboxDrainEngine(outbox, listOf(dispatcher)).drainOnce().done)
        assertEquals(listOf(parsed), published)
        assertEquals(PendingMutationStatus.Done.wireValue, dao.rows.values.single().status)
        assertEquals(original.idempotencyKey, api.lastRecognizeTextIdempotencyKey)
        assertEquals(original.expectedRowVersion, api.lastRecognizeTextRequest?.expectedRowVersion)
    }
}
