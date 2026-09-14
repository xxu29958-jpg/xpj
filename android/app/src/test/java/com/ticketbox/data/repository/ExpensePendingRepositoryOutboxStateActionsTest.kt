package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Pending commands preserve the reviewed fact until their original worker accepts them. */
internal class ExpensePendingRepositoryOutboxStateActionsTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test
    fun `confirm admission retains the pending fact and original token`() = runTest {
        assertStateAdmission(PendingMutationType.ConfirmExpense)
    }

    @Test
    fun `reject admission retains the pending fact rather than inventing a rejection`() = runTest {
        assertStateAdmission(PendingMutationType.RejectExpense)
    }

    @Test
    fun `mark duplicate admission does not invent the server review result`() = runTest {
        assertStateAdmission(PendingMutationType.MarkNotDuplicate)
    }

    @Test
    fun `retry OCR admission preserves the current snapshot and schedules the original`() = runTest {
        assertStateAdmission(PendingMutationType.RetryOcr)
    }

    private suspend fun assertStateAdmission(type: PendingMutationType) {
        val baseline = baselineExpense().copy(duplicateStatus = "suspected", duplicateOfId = 81L)
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val success = ApiResult.Success(successExpenseDto())
        val api = ApiServiceStub(confirmExpenseResult = success, rejectExpenseResult = success,
            markNotDuplicateResult = success, retryOcrResult = success)
        val repo = buildRepository(api, outbox)
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val accepted = when (type) {
            PendingMutationType.ConfirmExpense -> repo.confirmExpenseAllowingOffline(binding, baseline)
            PendingMutationType.RejectExpense -> repo.rejectExpenseAllowingOffline(binding, baseline)
            PendingMutationType.MarkNotDuplicate -> repo.markNotDuplicateAllowingOffline(binding, baseline)
            PendingMutationType.RetryOcr -> repo.retryOcrAllowingOffline(binding, baseline)
            else -> error("Unexpected state command")
        }.getOrThrow()
        val row = dao.rows.values.single()
        assertEquals(listOf(row.id), accepted.rowIds)
        assertEquals(baseline, accepted.expense)
        assertEquals(type.wireValue, row.type)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(binding.ownerKey, row.ownerKey)
        assertEquals(binding.ledgerId, row.ledgerId)
        assertEquals(binding.serverUrl, row.serverUrl)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertEquals(0L, moshi().adapter(ExpenseStateTokenRequest::class.java).fromJson(row.payload)?.expectedRowVersion)
        assertNotNull(row.idempotencyKey)
        assertNull(api.lastConfirmIdempotencyKey)
        assertNull(api.lastRejectIdempotencyKey)
        assertNull(api.lastMarkNotDuplicateIdempotencyKey)
        assertNull(api.lastRetryOcrIdempotencyKey)
    }

    @Test
    fun `confirm waits behind a persisted save with both original tokens unchanged`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val api = ApiServiceStub(confirmExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox)
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val saved = repo.saveExpenseAllowingOffline(binding, baseline.id, draft, baseline).getOrThrow()
        val confirmed = repo.confirmExpenseAllowingOffline(binding, baseline).getOrThrow()
        val rows = dao.rows.values.toList()
        assertEquals(listOf(PendingMutationType.PatchExpense.wireValue, PendingMutationType.ConfirmExpense.wireValue), rows.map { it.type })
        assertEquals(rows.map { it.id }, saved.rowIds + confirmed.rowIds)
        assertEquals(listOf(baseline.rowVersion, baseline.rowVersion), rows.map { it.expectedRowVersion })
        assertEquals("pending", confirmed.expense.status)
        assertNull(api.lastConfirmIdempotencyKey)
    }

    @Test
    fun `bulk confirmation preserves each original without publishing confirmed facts`() = runTest {
        val expenses = listOf(baselineExpense(), baselineExpense().copy(id = 43L, publicId = "second-expense", rowVersion = 6L))
        val dao = FakePendingMutationDao()
        val api = ApiServiceStub(confirmExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, testOutboxRepository(dao))
        val accepted = repo.confirmExpenses(requireNotNull(repo.captureDeferredLedgerBinding()), expenses).getOrThrow()
        val rows = dao.rows.values.toList()
        assertEquals(listOf("expense:42", "expense:43"), rows.map { it.targetId })
        assertEquals(listOf(1L, 6L), rows.map { it.expectedRowVersion })
        assertTrue(rows.all { it.type == PendingMutationType.ConfirmExpense.wireValue && it.status == PendingMutationStatus.Pending.wireValue })
        assertEquals(2, rows.mapNotNull { it.idempotencyKey }.distinct().size)
        assertEquals(rows.map { it.id }, accepted.flatMap { it.rowIds })
        assertEquals(expenses, accepted.map { it.expense })
        assertNull(api.lastConfirmIdempotencyKey)
    }

    @Test
    fun `acknowledge IOException returns Queued acknowledged-projection + enqueues row`() = runTest {
        val baseline = baselineExpense()
        val current = mismatchKnownItems()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(extras = ApiServiceStubExtras(acknowledgeException = IOException("net out")))
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.acknowledgeItemsMismatchAllowingOffline(baseline, current)
            .getOrThrow() as ItemsAckOutcome.Queued

        // Optimistic projection flips the items-sum status to acknowledged.
        assertEquals("mismatch_acknowledged", outcome.items.itemsSumStatus)
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.AcknowledgeItemsMismatch.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed the token: ${row.payload}",
        )
        // ADR-0042: direct attempt + enqueued row share one intent-time key.
        assertNotNull(row.idempotencyKey, "AcknowledgeItemsMismatch row must carry an idempotency key")
        assertEquals(api.lastAcknowledgeIdempotencyKey, row.idempotencyKey)
    }

    @Test
    fun `acknowledge direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val current = mismatchKnownItems()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        // acknowledgeException = null → success path.
        val api = ApiServiceStub()
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.acknowledgeItemsMismatchAllowingOffline(baseline, current).getOrThrow()

        assertTrue(outcome is ItemsAckOutcome.Synced)
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `acknowledge HttpException 409 surfaces as failure, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val current = mismatchKnownItems()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(
            extras = ApiServiceStubExtras(
                acknowledgeException = httpException(409, """{"error":"state_conflict","message":"账单已修改"}"""),
            ),
        )
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val result = repo.acknowledgeItemsMismatchAllowingOffline(baseline, current)

        assertTrue(result.isFailure, "409 must surface, not silently queue")
        assertEquals(0, dao.rows.size)
    }

    // endregion
}
