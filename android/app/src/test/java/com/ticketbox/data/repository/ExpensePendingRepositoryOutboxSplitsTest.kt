package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice E-1 splits-editor offline fallback
 * (``replaceExpenseSplitsAllowingOffline``). Mirrors
 * [ExpensePendingRepositoryOutboxItemsAndQueueTest]'s items coverage: an
 * IOException returns an optimistic [ReplaceSplitsOutcome.Queued] and enqueues a
 * body-carrying row whose token is stripped to zero (the row is the source of
 * truth) and whose idempotency key matches the direct PUT; a direct 2xx returns
 * [ReplaceSplitsOutcome.Synced] with no enqueue.
 *
 * Shared identity/session setup lives in [ExpensePendingRepositoryOutboxTestBase].
 */
internal class ExpensePendingRepositoryOutboxSplitsTest : ExpensePendingRepositoryOutboxTestBase() {

    private val splitDrafts: List<ExpenseSplitDraft> = listOf(
        ExpenseSplitDraft(memberId = 12L, amountCents = 2500L, note = null),
    )

    private fun splitsCurrent(): ExpenseSplits = ExpenseSplits(
        expenseId = 42L,
        parentAmountCents = 12345L,
        splitsTotalAmountCents = 12345L,
        mismatchCents = 0L,
        splits = emptyList(),
    )

    private fun splitsRepo(api: ApiService, outbox: OutboxRepository): ExpenseRepository = ExpenseRepository(
        expenseDao = FakeExpenseDao(),
        apiClient = TestApiServiceFactory(api),
        settingsStore = seededSettingsStore(),
        tokenStore = seededTokenStore(),
        deviceNameProvider = { "Android Test" },
        outbox = outbox,
        replaceSplitsAdapter = moshi().adapter(ExpenseSplitReplaceRequestDto::class.java),
    )

    @Test
    fun `replaceSplits IOException returns Queued optimistic + enqueues body without token`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        // ADR-0042: capture the Idempotency-Key the repository supplied on the
        // direct PUT so we can assert the enqueued row carries the SAME key.
        var directIdempotencyKey: String? = null
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun replaceExpenseSplits(
                id: String,
                request: ExpenseSplitReplaceRequestDto,
                idempotencyKey: String?,
            ): ExpenseSplitsResponseDto {
                directIdempotencyKey = idempotencyKey
                throw IOException("net out")
            }
        }

        val outcome = splitsRepo(api, outbox)
            .replaceExpenseSplitsAllowingOffline(baseline, splitDrafts, splitsCurrent())
            .getOrThrow() as ReplaceSplitsOutcome.Queued

        // Optimistic projection surfaces the user's edit + recomputed total.
        assertEquals(1, outcome.splits.splits.size)
        assertEquals(12L, outcome.splits.splits.first().memberId)
        assertEquals(2500L, outcome.splits.splitsTotalAmountCents)

        // One row enqueued; token authoritative on the row, stripped from payload.
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.ReplaceSplits.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertTrue("\"member_id\":12" in row.payload, "payload must carry the edit: ${row.payload}")
        assertTrue(
            "\"expected_row_version\":0" in row.payload,
            "payload token must be stripped to zero (row is the source of truth): ${row.payload}",
        )
        // ADR-0042: the direct attempt + the enqueued row share ONE intent-time
        // key — that's what lets a committed-but-unseen replay HIT the server's
        // recorded success instead of false-409ing on the stale token.
        assertEquals(
            directIdempotencyKey,
            row.idempotencyKey,
            "enqueued row must carry the same key the direct PUT used",
        )
        assertTrue(row.idempotencyKey != null, "ReplaceSplits row must carry an idempotency key")
    }

    @Test
    fun `replaceSplits direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun replaceExpenseSplits(
                id: String,
                request: ExpenseSplitReplaceRequestDto,
                idempotencyKey: String?,
            ): ExpenseSplitsResponseDto = ExpenseSplitsResponseDto(
                expenseId = 42L,
                rowVersion = 2L,
                parentAmountCents = 12345L,
                splitsTotalAmountCents = 2500L,
                mismatchCents = -9845L,
                splits = emptyList(),
            )
        }

        val outcome = splitsRepo(api, outbox)
            .replaceExpenseSplitsAllowingOffline(baseline, splitDrafts, splitsCurrent())
            .getOrThrow()

        assertTrue(outcome is ReplaceSplitsOutcome.Synced)
        assertEquals(0, dao.rows.size, "no row should be enqueued on direct success")
    }
}
