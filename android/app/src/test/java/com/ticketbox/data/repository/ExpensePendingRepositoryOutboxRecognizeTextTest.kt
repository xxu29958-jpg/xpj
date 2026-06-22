package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice E-2 "粘贴文字识别" offline fallback
 * (``recognizeTextAllowingOffline``). Body-carrying like
 * [ExpensePendingRepositoryOutboxSplitsTest] (the pasted ``raw_text`` is
 * persisted on the row), but the response is an [Expense] so the outcome reuses
 * [ExpenseStateOutcome] (like retry-OCR): an IOException returns
 * [ExpenseStateOutcome.Queued] with the expense UNCHANGED (the server does the
 * parsing — nothing to project optimistically) and enqueues a body-carrying row
 * whose token is stripped to zero and whose idempotency key matches the direct
 * POST; a direct 2xx returns [ExpenseStateOutcome.Synced] with the parsed expense
 * and no enqueue.
 *
 * Shared identity/session setup lives in [ExpensePendingRepositoryOutboxTestBase].
 */
internal class ExpensePendingRepositoryOutboxRecognizeTextTest : ExpensePendingRepositoryOutboxTestBase() {

    private val pastedText = "星巴克 拿铁 ¥35 2026-05-20"

    private fun recognizeTextRepo(api: ApiService, outbox: OutboxRepository): ExpenseRepository = ExpenseRepository(
        expenseDao = FakeExpenseDao(),
        apiClient = TestApiServiceFactory(api),
        settingsStore = seededSettingsStore(),
        tokenStore = seededTokenStore(),
        deviceNameProvider = { "Android Test" },
        outbox = outbox,
        recognizeTextAdapter = moshi().adapter(ExpenseRecognizeTextRequestDto::class.java),
    )

    @Test
    fun `recognizeText IOException returns Queued unchanged + enqueues body without token`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        // ADR-0042: capture the Idempotency-Key the repository supplied on the
        // direct POST so we can assert the enqueued row carries the SAME key.
        var directIdempotencyKey: String? = null
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun recognizeText(
                id: String,
                request: ExpenseRecognizeTextRequestDto,
                idempotencyKey: String?,
            ): ExpenseDto {
                directIdempotencyKey = idempotencyKey
                throw IOException("net out")
            }
        }

        val outcome = recognizeTextRepo(api, outbox)
            .recognizeTextAllowingOffline(baseline, pastedText)
            .getOrThrow()

        // Queued is the expense UNCHANGED — the server parses, nothing to project.
        assertTrue(outcome is ExpenseStateOutcome.Queued)
        assertEquals(baseline, outcome.expense, "offline Queued expense must be the unchanged baseline")

        // One row enqueued; token authoritative on the row, stripped from payload,
        // but the pasted raw_text is preserved so the replay re-sends it.
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.RecognizeText.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertTrue("\"raw_text\":\"$pastedText\"" in row.payload, "payload must carry the pasted text: ${row.payload}")
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
            "enqueued row must carry the same key the direct POST used",
        )
        assertTrue(row.idempotencyKey != null, "RecognizeText row must carry an idempotency key")
    }

    @Test
    fun `recognizeText direct 2xx returns Synced parsed expense, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun recognizeText(
                id: String,
                request: ExpenseRecognizeTextRequestDto,
                idempotencyKey: String?,
            ): ExpenseDto = successExpenseDto()
        }

        val outcome = recognizeTextRepo(api, outbox)
            .recognizeTextAllowingOffline(baseline, pastedText)
            .getOrThrow()

        assertTrue(outcome is ExpenseStateOutcome.Synced)
        // Synced carries the server-parsed expense (row_version bumped to 2).
        assertEquals(2L, outcome.expense.rowVersion)
        assertEquals(0, dao.rows.size, "no row should be enqueued on direct success")
    }
}
