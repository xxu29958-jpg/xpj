package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionResponseDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseSplitDraft
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

internal class ExpenseCorrectionRepositoryTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test
    fun `reason code point limit is enforced before enqueue while 500 stays legal`() = runTest {
        for (character in listOf("改", "\uD83D\uDE42")) {
            for (length in listOf(501, 500)) {
                val queue = FakePendingMutationDao()
                val repo = buildCorrectionRepository(FakeApiService(mutableListOf(), 0), outbox = testOutboxRepository(queue))
                val reason = character.repeat(length)
                val result = submit(repo, baselineExpense().copy(status = "confirmed", rowVersion = 7),
                    ExpenseCorrectionDraft(reason, merchant = "核对后的商家"))

                assertEquals(length == 500, result.isSuccess, "Reason length follows API Unicode characters, not UTF-16 units")
                if (length == 501) {
                    assertTrue(queue.rows.isEmpty(), "A permanently invalid command must not be scheduled")
                } else {
                    val pending = repo.observeCorrections().first().corrections.single()
                    assertEquals(reason, assertNotNull(pending.intent).request.reason)
                    assertEquals(7L, pending.row.expectedRowVersion)
                    assertNotNull(pending.row.idempotencyKey)
                }
            }
        }
    }

    @Test
    fun `stored overlong original reason remains visible but cannot retry or change its command`() = runTest {
        for (character in listOf("改", "\uD83D\uDE42")) {
            val queue = FakePendingMutationDao()
            val outbox = testOutboxRepository(queue)
            val repo = buildCorrectionRepository(FakeApiService(mutableListOf(), 0), outbox = outbox)
            val binding = assertNotNull(repo.observeCorrections().first().access).binding
            val payload = ExpenseCorrectionPayload(1, 42L, "原商家", "CNY", 1200L, "CNY",
                binding.ownerKey, binding.ledgerId, binding.sessionGeneration, binding.bindingRevision,
                ExpenseCorrectionRequestDto(7L, character.repeat(501), note = "原命令内容"))
            val json = OutboxAdapterGraph().correctionAdapter.toJson(payload)
            val id = outbox.enqueue(PendingMutationType.CorrectExpense, "expense:42", json, 7L, "original-invalid-key")
            outbox.markFailed(id, "validation_error")
            val original = queue.rows.getValue(id)
            val pending = repo.observeCorrections().first().corrections.single()

            assertFalse(pending.hasSupportedIntent, "A known format with an impossible reason is not replayable")
            assertFalse(pending.canRetry)
            assertTrue(pending.canDiscard)
            assertEquals(json, pending.row.payloadJson)
            assertTrue(repo.recoverCorrection(binding, id, drop = false).isFailure)
            assertEquals(original, queue.rows.getValue(id), "Refusal preserves original key, OCC, binding and payload")
            repo.recoverCorrection(binding, id, drop = true).getOrThrow()
            assertTrue(queue.rows.isEmpty())
        }
    }

    @Test
    fun `composite correction is persisted before scheduling without waiting for a direct request`() = runTest {
        val mutationDao = FakePendingMutationDao()
        var scheduledRow: PendingMutationEntity? = null
        val outbox = testOutboxRepository(
            dao = mutationDao,
            onEnqueued = { scheduledRow = mutationDao.rows.values.singleOrNull() },
        )
        var directRequests = 0
        val transportEntered = CompletableDeferred<Unit>()
        val api = object : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun correctExpense(
                id: String,
                request: ExpenseCorrectionRequestDto,
                idempotencyKey: String?,
            ): ExpenseCorrectionResponseDto {
                directRequests++
                transportEntered.complete(Unit)
                awaitCancellation()
            }
        }
        val repo = buildCorrectionRepository(api = api, outbox = outbox)
        val baseline = baselineExpense().copy(
            status = "confirmed", confirmedAt = "2026-05-20T12:30:00Z", rowVersion = 7L, factRevision = 3L,
        )
        val correction = ExpenseCorrectionDraft(
            reason = "校正金额、明细与分摊",
            originalCurrencyCode = CurrencyCode.CNY,
            originalAmountMinor = 1_200L,
            category = "餐饮",
            note = "家庭午餐",
            expenseTimeChanged = true,
            valueScore = 4,
            valueScoreChanged = true,
            regretScoreChanged = true,
            items = listOf(ExpenseItemDraft("午餐", "1", 1_200L, 1_200L, "餐饮", null, null)),
            splits = listOf(ExpenseSplitDraft(memberId = 7L, amountCents = 1_200L, note = "共同用餐")),
        )
        val submission = async { submit(repo, baseline, correction) }

        try {
            select {
                submission.onAwait { }
                transportEntered.onAwait { }
            }
            if (submission.isCompleted) submission.await().getOrThrow()

            assertEquals(1, mutationDao.rows.size, "a suspended first request must not leave the submitted intent only in memory")
            val original = mutationDao.rows.values.single()
            assertEquals(original, scheduledRow, "the scheduler must observe the complete already-persisted row")
            assertEquals(PendingMutationType.CorrectExpense.wireValue, original.type)
            assertEquals("expense:42", original.targetId)
            assertEquals(7L, original.expectedRowVersion)
            assertNotNull(original.idempotencyKey)
            assertEquals(0, directRequests, "only the Outbox dispatcher may send the saved command")
            assertTrue(submission.isCompleted, "local acceptance cannot wait for a network response")
            assertTrue(submission.await().isSuccess)
        } finally {
            submission.cancelAndJoin()
        }
    }

    @Test
    fun `full original command round trips without projecting a new canonical fact or recomputing FX`() = runTest {
        val dao = FakeExpenseDao()
        val queue = FakePendingMutationDao()
        val repo = buildCorrectionRepository(FakeApiService(mutableListOf(), 0), dao, testOutboxRepository(queue))
        val baseline = baselineExpense().copy(status = "confirmed", rowVersion = 7, factRevision = 3,
            homeCurrencyCode = "CNY", originalCurrencyCode = CurrencyCode.JPY, originalCurrencyCodeRaw = "JPY",
            originalAmountMinor = 1200, amountCents = 6000, homeAmountCents = 6000, exchangeRateToCny = "0.05", fxStatus = "ready")
        val draft = ExpenseCorrectionDraft(reason = " 日期、原币与集合 ", originalCurrencyCode = CurrencyCode.USD,
            originalAmountMinor = 1300, merchant = "新商家", category = "购物", note = "", tags = "",
            expenseTimeChanged = true, valueScoreChanged = true, valueScore = 4, regretScoreChanged = true,
            items = listOf(ExpenseItemDraft("午餐", "1", 1300, 1300, "餐饮", "原文", null)),
            splits = emptyList())

        val id = submit(repo, baseline, draft).getOrThrow()
        val pending = repo.observeCorrections().first().corrections.single()
        val stored = assertNotNull(pending.intent)
        assertEquals(id, pending.row.id)
        assertEquals(draft.toRequest(7), stored.request)
        assertEquals(7L, stored.request.expectedRowVersion)
        assertEquals("JPY", stored.originalCurrencyCode)
        assertEquals(1200L, stored.originalAmountMinor)
        assertEquals("CNY", stored.homeCurrencyCode)
        assertEquals(baseline.merchant, stored.originalMerchant)
        assertEquals(pending.row.ownerKey, stored.ownerKey)
        assertEquals(pending.row.ledgerId, stored.ledgerId)
        assertNull(stored.request.amountCents, "the client must not recompute the target's home FX amount")
        assertTrue(stored.request.expenseTime.changed)
        assertNull(stored.request.expenseTime.value)
        assertEquals(4, stored.request.valueScore.value)
        assertTrue(stored.request.regretScore.changed)
        assertNull(stored.request.regretScore.value)
        assertEquals(emptyList(), stored.request.splits, "explicit empty replacement survives")
        assertEquals("原文", stored.request.items?.single()?.rawText)
        assertNull(dao.findByServerId("owner", baseline.id), "local acceptance is no canonical cache write")
        assertFalse(pending.delivered)
    }

    @Test
    fun `a second correction cannot skip an unresolved original submission`() = runTest {
        val queue = FakePendingMutationDao()
        val repo = buildCorrectionRepository(FakeApiService(mutableListOf(), 0), outbox = testOutboxRepository(queue))
        val baseline = baselineExpense().copy(status = "confirmed", rowVersion = 7)
        submit(repo, baseline, ExpenseCorrectionDraft("第一次", note = "原意图")).getOrThrow()
        val original = queue.rows.values.single()
        assertTrue(submit(repo, baseline, ExpenseCorrectionDraft("第二次", note = "不得替代")).isFailure)
        assertEquals(original, queue.rows.values.single())
    }

    @Test
    fun `old normalized intent remains readable but cannot retry and explicit discard preserves the fact`() = runTest {
        val queue = FakePendingMutationDao()
        val outbox = testOutboxRepository(queue)
        val repo = buildCorrectionRepository(FakeApiService(mutableListOf(), 0), outbox = outbox)
        val json = OutboxAdapterGraph().legacyCorrectionAdapter.toJson(ExpenseCorrectionRequestDto(0, "旧明细", items = emptyList()))
        val id = outbox.enqueue(PendingMutationType.CorrectExpense, "expense:42", json, 9, "old-key")
        outbox.markFailed(id, "correction_requires_review")
        val observed = repo.observeCorrections().first()
        val access = assertNotNull(observed.access)
        val pending = observed.corrections.single()
        assertNull(pending.intent)
        assertEquals("旧明细", pending.legacyRequest?.reason)
        assertEquals(emptyList(), pending.legacyRequest?.items)
        val original = queue.rows.getValue(id)
        assertTrue(repo.recoverCorrection(access.binding, id, drop = false).isFailure)
        assertEquals(original, queue.rows.getValue(id))
        repo.recoverCorrection(access.binding, id, drop = true).getOrThrow()
        assertTrue(queue.rows.isEmpty())
    }

    @Test
    fun `old DONE is unproven and an unknown payload retains its original bytes until explicit discard`() = runTest {
        val queue = FakePendingMutationDao()
        val outbox = testOutboxRepository(queue)
        val repo = buildCorrectionRepository(FakeApiService(mutableListOf(), 0), outbox = outbox)
        val id = outbox.enqueue(PendingMutationType.CorrectExpense, "expense:42", "{unknown format}", 9, "old-key")
        outbox.markDone(id)
        val observed = repo.observeCorrections().first()
        val pending = observed.corrections.single()
        assertFalse(pending.delivered)
        assertTrue(pending.canDiscard)
        assertFalse(pending.canRetry)
        assertEquals("{unknown format}", queue.rows.getValue(id).payload)
        repo.recoverCorrection(assertNotNull(observed.access).binding, id, true).getOrThrow()
        assertTrue(queue.rows.isEmpty())
    }

    @Test
    fun `zero OCC and changed logical binding refuse before publishing`() = runTest {
        val queue = FakePendingMutationDao()
        val repo = buildCorrectionRepository(FakeApiService(mutableListOf(), 0), outbox = testOutboxRepository(queue))
        val baseline = baselineExpense().copy(status = "confirmed", rowVersion = 0)
        val binding = assertNotNull(repo.observeCorrections().first().access).binding
        assertTrue(repo.submitCorrection(binding, baseline, ExpenseCorrectionDraft("更正", note = "草稿")).isFailure)
        assertTrue(repo.submitCorrection(binding.copy(bindingRevision = "different"), baseline.copy(rowVersion = 7),
            ExpenseCorrectionDraft("更正", note = "草稿")).isFailure)
        assertTrue(queue.rows.isEmpty())
    }

    @Test
    fun `expired supported submission preserves identity and offers only explicit review or discard`() = runTest {
        val queue = FakePendingMutationDao()
        val clock = java.time.Clock.fixed(java.time.Instant.parse("2026-09-06T00:00:00Z"), java.time.ZoneOffset.UTC)
        val outbox = testOutboxRepository(queue, clock)
        val repo = buildCorrectionRepository(FakeApiService(mutableListOf(), 0), outbox = outbox)
        val id = submit(repo, baselineExpense().copy(status = "confirmed", rowVersion = 7),
            ExpenseCorrectionDraft("原始到期提交", note = "内容仍在")).getOrThrow()
        val original = queue.rows.getValue(id)
        outbox.reapExpiredPending(java.time.Instant.parse("2026-09-14T00:00:00Z").toEpochMilli())
        val observed = repo.observeCorrections().first()
        assertFalse(observed.corrections.single().canRetry)
        assertTrue(repo.recoverCorrection(assertNotNull(observed.access).binding, id, false).isFailure)
        val retained = queue.rows.getValue(id)
        assertEquals(original.payload, retained.payload)
        assertEquals(original.idempotencyKey, retained.idempotencyKey)
        assertEquals(original.expectedRowVersion, retained.expectedRowVersion)
        assertTrue(observed.corrections.single().canDiscard)
    }

    private suspend fun submit(repo: ExpenseRepository, baseline: Expense, draft: ExpenseCorrectionDraft) =
        repo.submitCorrection(assertNotNull(repo.observeCorrections().first().access).binding, baseline, draft)

    private fun buildCorrectionRepository(api: ApiService, expenseDao: FakeExpenseDao = FakeExpenseDao(),
        outbox: OutboxRepository = testOutboxRepository(FakePendingMutationDao())): ExpenseRepository = ExpenseRepository(
        expenseDao = expenseDao,
        binding = testServerSessionBinding(apiClient = TestApiServiceFactory(api), settingsStore = seededSettingsStore(),
            tokenStore = seededTokenStore()),
        deviceNameProvider = { "Android Test" }, offlineMutations = testExpenseOfflineMutationWiring(outbox))
}
