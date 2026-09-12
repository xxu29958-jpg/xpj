package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.FxContract
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Admission persists reviewed input; only the existing worker receives HTTP outcomes. */
internal class ExpensePendingRepositoryOutboxFallbackTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test
    fun `online save persists its draft and original command without calling HTTP`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox)
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())

        val accepted = repo.saveExpenseAllowingOffline(binding, baseline.id, draft, baseline).getOrThrow()

        val row = dao.rows.values.single()
        assertEquals(listOf(row.id), accepted.rowIds)
        assertEquals("新商家", accepted.expense.merchant)
        assertEquals(baseline.status, accepted.expense.status)
        assertEquals(baseline.rowVersion, accepted.expense.rowVersion)
        assertEquals(baseline.updatedAt, accepted.expense.updatedAt)
        assertEquals(PendingMutationType.PatchExpense.wireValue, row.type)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(binding.ledgerId, row.ledgerId)
        assertEquals(binding.ownerKey, row.ownerKey)
        assertEquals(binding.serverUrl, row.serverUrl)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertNotNull(row.idempotencyKey)
        assertNull(api.lastIdempotencyKey, "Admission must not attempt HTTP")
        val request = requireNotNull(moshi().adapter(ExpenseUpdateRequest::class.java).fromJson(row.payload))
        assertEquals("新商家", request.merchant)
        assertNull(request.expectedRowVersion)
    }

    @Test
    fun `save joins the existing same-target FIFO without sending inline`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox)
        outbox.enqueue(PendingMutationType.ConfirmExpense, "expense:${baseline.id}", "{}",
            baseline.rowVersion, idempotencyKey = "original-confirm-key")
        val accepted = repo.saveExpenseAllowingOffline(requireNotNull(repo.captureDeferredLedgerBinding()),
            baseline.id, draft, baseline).getOrThrow()
        val rows = dao.rows.values.toList()
        assertEquals(listOf(PendingMutationType.ConfirmExpense.wireValue, PendingMutationType.PatchExpense.wireValue), rows.map { it.type })
        assertEquals(listOf(rows.last().id), accepted.rowIds)
        assertEquals(listOf(baseline.rowVersion, baseline.rowVersion), rows.map { it.expectedRowVersion })
        assertNull(api.lastIdempotencyKey)
    }

    @Test
    fun `manual exchange rate survives queued PatchExpense without fabricating ready snapshot`() = runTest {
        val baseline = baselineExpense().copy(
            amountCents = null,
            homeAmountCents = null,
            originalCurrency = CurrencyCode.USD,
            originalCurrencyCode = CurrencyCode.USD,
            originalCurrencyCodeRaw = "USD",
            originalAmountMinor = 1200L,
            fxRate = null,
            exchangeRateToCny = null,
            fxStatus = FxContract.StatusPending,
        )
        val manualRateDraft = draft.copy(
            amountCents = null,
            originalCurrencyCode = CurrencyCode.USD,
            originalAmountMinor = 1200L,
            manualExchangeRate = "7.20",
        )
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, adapter)

        val outcome = repo.saveExpenseAllowingOffline(requireNotNull(repo.captureDeferredLedgerBinding()), baseline.id, manualRateDraft, baseline)
            .getOrThrow()

        val row = dao.rows.values.single()
        assertTrue("\"manual_exchange_rate\":\"7.20\"" in row.payload)
        assertEquals(FxContract.StatusPending, outcome.expense.fxStatus)
        assertNull(outcome.expense.homeAmountCents)
        assertNull(outcome.expense.exchangeRateToCny)
    }

    @Test
    fun `queued manual re-rate clears stale ready snapshot until canonical response`() = runTest {
        val baseline = baselineExpense().copy(
            amountCents = 8640L,
            homeAmountCents = 8640L,
            originalCurrency = CurrencyCode.USD,
            originalCurrencyCode = CurrencyCode.USD,
            originalCurrencyCodeRaw = "USD",
            originalAmountMinor = 1200L,
            fxRate = "7.20",
            fxRateDate = "2026-09-05",
            fxSource = "manual",
            exchangeRateToCny = "7.20",
            exchangeRateDate = "2026-09-05",
            exchangeRateSource = "manual",
            fxStatus = FxContract.StatusReady,
        )
        val manualRateDraft = draft.copy(
            amountCents = null,
            originalCurrencyCode = CurrencyCode.USD,
            originalAmountMinor = 1200L,
            manualExchangeRate = "7.25",
        )
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseUpdateRequest::class.java)
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(IOException("net out")))
        val repo = buildRepository(api, outbox, adapter)

        val outcome = repo.saveExpenseAllowingOffline(requireNotNull(repo.captureDeferredLedgerBinding()), baseline.id, manualRateDraft, baseline)
            .getOrThrow()

        assertEquals(FxContract.StatusPending, outcome.expense.fxStatus)
        assertNull(outcome.expense.amountCents)
        assertNull(outcome.expense.homeAmountCents)
        assertNull(outcome.expense.fxRate)
        assertNull(outcome.expense.fxRateDate)
        assertNull(outcome.expense.fxSource)
        assertNull(outcome.expense.exchangeRateToCny)
        assertNull(outcome.expense.exchangeRateDate)
        assertNull(outcome.expense.exchangeRateSource)
    }

    @Test
    fun `a server conflict belongs to the persisted original after dispatch`() = runTest {
        assertDeferredFailure(409, PendingMutationStatus.Conflict)
    }

    @Test
    fun `server validation failure keeps the persisted original for review`() = runTest {
        assertDeferredFailure(422, PendingMutationStatus.Failed)
    }

    @Test
    fun `transient server failure leaves the original pending for the worker`() = runTest {
        assertDeferredFailure(500, PendingMutationStatus.Pending)
    }

    private suspend fun assertDeferredFailure(code: Int, status: PendingMutationStatus) {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val body = if (code == 409) """{"error":"state_conflict"}""" else """{"error":"server_refusal"}"""
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Throw(httpException(code, body)))
        val repo = buildRepository(api, outbox)
        val accepted = repo.saveExpenseAllowingOffline(requireNotNull(repo.captureDeferredLedgerBinding()),
            baseline.id, draft, baseline).getOrThrow()
        val original = dao.rows.values.single()
        assertEquals(listOf(original.id), accepted.rowIds)
        assertNull(api.lastIdempotencyKey)
        val dispatcher = PatchExpenseDispatcher(apiProvider = { api },
            payloadAdapter = moshi().adapter(ExpenseUpdateRequest::class.java),
            publishExpense = { _, _ -> error("Rejected HTTP must not publish a snapshot") })
        OutboxDrainEngine(outbox, listOf(dispatcher)).drainOnce()
        val retained = dao.rows.values.single()
        assertEquals(status.wireValue, retained.status)
        assertEquals(original.idempotencyKey, api.lastIdempotencyKey)
        assertEquals(original.idempotencyKey, retained.idempotencyKey)
        assertEquals(original.payload, retained.payload)
        assertEquals(original.expectedRowVersion, retained.expectedRowVersion)
        assertEquals(original.ownerKey, retained.ownerKey)
        assertEquals(original.ledgerId, retained.ledgerId)
    }

    @Test
    fun `a changed binding rejects the original save before admission or HTTP`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val session = seededTokenStore()
        val outbox = testOutboxRepository(dao, bindingProvider = { session.sessionStore.currentSession().toOutboxBinding() })
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox, session = session)
        val original = requireNotNull(repo.captureDeferredLedgerBinding())
        session.switchLedgerForFixture("another-ledger", "另一个账本")
        val result = repo.saveExpenseAllowingOffline(original, baseline.id, draft, baseline)
        assertTrue(result.isFailure)
        assertTrue(dao.rows.isEmpty())
        assertNull(api.lastIdempotencyKey)
    }

    @Test
    fun `save and confirm publishes one batch with both original commands`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val api = ApiServiceStub(updateExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox)
        val accepted = repo.saveAndConfirmExpense(requireNotNull(repo.captureDeferredLedgerBinding()), baseline, draft).getOrThrow()
        val rows = dao.rows.values.toList()
        assertEquals(listOf(PendingMutationType.PatchExpense.wireValue, PendingMutationType.ConfirmExpense.wireValue), rows.map { it.type })
        assertEquals(rows.map { it.id }, accepted.rowIds)
        assertEquals(listOf(baseline.rowVersion, baseline.rowVersion), rows.map { it.expectedRowVersion })
        assertEquals(2, rows.mapNotNull { it.idempotencyKey }.distinct().size)
        assertEquals(1, rows.map { Triple(it.ownerKey, it.ledgerId, it.targetId) }.distinct().size)
        assertEquals("pending", accepted.expense.status)
        assertEquals(baseline.rowVersion, accepted.expense.rowVersion)
        assertEquals("新商家", accepted.expense.merchant)
        assertNull(api.lastIdempotencyKey)
        assertNull(api.lastConfirmIdempotencyKey)
    }
}
