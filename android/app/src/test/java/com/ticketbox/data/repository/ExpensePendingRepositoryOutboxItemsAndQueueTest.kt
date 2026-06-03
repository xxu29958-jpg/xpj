package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0038 items-editor offline fallback
 * (``replaceExpenseItemsAllowingOffline``) plus the
 * [OutboxRepository] queue-lifecycle invariants (round-7 P2 +
 * round-8): best-effort ``onEnqueued`` / ``onClearAll`` callbacks and
 * the session-boundary ``clearAll`` contract.
 *
 * Shared setup lives in [ExpensePendingRepositoryOutboxTestBase].
 */
internal class ExpensePendingRepositoryOutboxItemsAndQueueTest : ExpensePendingRepositoryOutboxTestBase() {

    // region — replaceExpenseItemsAllowingOffline (PR-D items editor)

    @Test
    fun `replaceItems IOException returns Queued optimistic + enqueues body without token`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun replaceExpenseItems(
                id: Long,
                request: ExpenseItemReplaceRequestDto,
            ): ExpenseItemsResponseDto = throw IOException("net out")
        }

        val outcome = itemsRepo(api, outbox)
            .replaceExpenseItemsAllowingOffline(baseline, itemDrafts, itemsCurrent())
            .getOrThrow() as ReplaceItemsOutcome.Queued

        // Optimistic projection surfaces the user's edit + recomputed total.
        assertEquals(1, outcome.items.items.size)
        assertEquals("咖啡", outcome.items.items.first().name)
        assertEquals(2500L, outcome.items.itemsTotalAmountCents)

        // One row enqueued; token authoritative on the row, stripped from payload.
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.ReplaceItems.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertTrue("咖啡" in row.payload, "payload must carry the edit: ${row.payload}")
        assertTrue(
            "\"expected_row_version\":0" in row.payload,
            "payload token must be stripped to zero (row is the source of truth): ${row.payload}",
        )
    }

    @Test
    fun `replaceItems direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun replaceExpenseItems(
                id: Long,
                request: ExpenseItemReplaceRequestDto,
            ): ExpenseItemsResponseDto = ExpenseItemsResponseDto(
                expenseId = 42L,
                rowVersion = 1L,
                parentAmountCents = 12345L,
                itemsTotalAmountCents = 2500L,
                mismatchCents = -9845L,
                itemsSumStatus = "mismatch_known",
                items = emptyList(),
            )
        }

        val outcome = itemsRepo(api, outbox)
            .replaceExpenseItemsAllowingOffline(baseline, itemDrafts, itemsCurrent())
            .getOrThrow()

        assertTrue(outcome is ReplaceItemsOutcome.Synced)
        assertEquals(0, dao.rows.size, "no row should be enqueued on direct success")
    }

    // endregion

    // region — OutboxRepository invariants (round-7 P2 + round-8)

    @Test
    fun `OutboxRepository enqueue does not fail when onEnqueued throws`() = runTest {
        // Codex round-7 P2: onEnqueued is a best-effort scheduler
        // wake. If WorkManager throws, the row is already in the
        // DAO and periodic worker will pick it up. Round-8 P2
        // narrowed the catch from Throwable to Exception so
        // JVM-level Errors propagate.
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(
            dao = dao,
            onEnqueued = { throw IllegalStateException("simulated WorkManager fault") },
        )

        val rowId = outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:42",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )

        assertTrue(rowId > 0)
        assertEquals(1, dao.rows.size)
    }

    @Test
    fun `clearAll drops every row and fires onClearAll`() = runTest {
        // codex round-8 P1: session-boundary lifecycle hook.
        // clearAll must (a) wipe the DAO and (b) signal the
        // scheduler-cancel callback.
        val dao = FakePendingMutationDao()
        var cancelled = false
        val outbox = OutboxRepository(
            dao = dao,
            onClearAll = { cancelled = true },
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 2L,
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedRowVersion = 3L,
        )

        val removed = outbox.clearAll()

        assertEquals(2, removed, "all rows reported as removed")
        assertEquals(0, dao.rows.size, "DAO is empty after clearAll")
        assertTrue(cancelled, "onClearAll must fire (scheduler-cancel signal)")
    }

    @Test
    fun `clearAll still succeeds when onClearAll throws (best-effort callback)`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(
            dao = dao,
            onClearAll = { throw IllegalStateException("simulated WorkManager.cancel fault") },
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 2L,
        )

        val removed = outbox.clearAll()

        assertEquals(1, removed)
        assertEquals(0, dao.rows.size)
    }

    // endregion
}
