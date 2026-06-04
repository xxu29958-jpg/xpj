package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.BatchApplyResult
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice C: the confirmed-expense batch field edit fans out into one
 * offline-aware PatchExpense per expense (``LedgerActions.applyConfirmedBatch``
 * → ``ExpensePendingRepository.applyConfirmedFieldsOffline``). These cases pin
 * the two things that matter:
 *
 *  - FIELD-SELECTIVE build: a tags-only batch must NOT carry a ``category`` key
 *    (and vice-versa). A tags-only edit routed through ``ExpenseDraft.toRequest()``
 *    would coerce a null category to "其他" and silently overwrite every target —
 *    the enqueued payload is the witness that we build the request directly.
 *  - PARTIAL SUCCESS: each expense's outcome (Synced / Queued / failed) is
 *    tallied independently, unlike the atomic /web batch endpoint.
 */
internal class ExpensePendingRepositoryBatchFanoutTest : ExpensePendingRepositoryOutboxTestBase() {

    @Test
    fun `category-only batch direct success sends category not tags, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.applyConfirmedBatch(listOf(baseline), category = "购物", tags = null)

        assertEquals(BatchApplyResult(synced = 1), result.getOrThrow())
        val request = assertNotNull(api.lastUpdateRequest)
        assertEquals("购物", request.category)
        assertEquals(null, request.tags, "category-only batch must leave tags untouched")
        assertNotNull(api.lastIdempotencyKey, "fan-out PATCH must send an Idempotency-Key")
        assertEquals(0, dao.rows.size, "direct success enqueues nothing")
    }

    @Test
    fun `tags-only batch offline enqueues payload with tags but no category`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.applyConfirmedBatch(listOf(baseline), category = null, tags = "出差")

        assertEquals(BatchApplyResult(queued = 1), result.getOrThrow())
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.PatchExpense.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertTrue("出差" in row.payload, "payload must carry the new tags: ${row.payload}")
        // The obstacle: a tags-only batch must NOT smuggle a category key — that
        // would overwrite every target's category (toRequest()'s null→"其他" trap).
        // Key-anchored ("category" as a JSON key) so a value can't false-trip it.
        assertFalse("\"category\"" in row.payload, "tags-only payload must omit category: ${row.payload}")
    }

    @Test
    fun `category-only batch offline enqueues payload with category but no tags`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, adapter)

        repo.applyConfirmedBatch(listOf(baseline), category = "购物", tags = null).getOrThrow()

        val row = dao.rows.values.single()
        assertTrue("购物" in row.payload, "payload must carry the new category: ${row.payload}")
        assertFalse("\"tags\"" in row.payload, "category-only payload must omit tags: ${row.payload}")
    }

    @Test
    fun `batch fans out one outbox row per expense when offline`() = runTest {
        val first = baselineExpense().copy(id = 1L)
        val second = baselineExpense().copy(id = 2L)
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.applyConfirmedBatch(listOf(first, second), category = "购物", tags = null)

        assertEquals(BatchApplyResult(queued = 2), result.getOrThrow())
        assertEquals(
            setOf("expense:1", "expense:2"),
            dao.rows.values.map { it.targetId }.toSet(),
        )
    }

    @Test
    fun `batch mixes synced, queued, and failed outcomes independently`() = runTest {
        val first = baselineExpense().copy(id = 1L)
        val second = baselineExpense().copy(id = 2L)
        val third = baselineExpense().copy(id = 3L)
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)
        val api = ApiServiceStub(
            updateExpenseResultById = mapOf(
                1L to ApiResult.Success(successExpenseDto()),
                2L to ApiResult.Throw(IOException("net out")),
                3L to ApiResult.Throw(httpException(409, """{"error":"state_conflict","message":"账单已修改"}""")),
            ),
        )
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.applyConfirmedBatch(listOf(first, second, third), category = "购物", tags = null)

        // Non-atomic fan-out: each expense's outcome is tallied independently —
        // a 409 on one row neither blocks the synced one nor the queued one.
        assertEquals(BatchApplyResult(synced = 1, queued = 1, failed = 1), result.getOrThrow())
        // Only the offline (IOException) row is enqueued; the 409 is a hard fail.
        assertEquals(listOf("expense:2"), dao.rows.values.map { it.targetId })
    }

    @Test
    fun `batch counts a 409 conflict as failed without enqueueing it`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)
        val api = ApiServiceStub(
            updateExpenseResult = ApiResult.Throw(
                httpException(409, """{"error":"state_conflict","message":"账单已修改"}"""),
            ),
        )
        val repo = buildRepository(api, outbox, adapter)

        val result = repo.applyConfirmedBatch(listOf(baseline), category = "购物", tags = null)

        assertEquals(BatchApplyResult(failed = 1), result.getOrThrow())
        assertEquals(0, dao.rows.size, "a hard 409 is not queued — it surfaces as needs-resync")
    }
}
