package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ExpenseFxRepositoryTest {
    @Test
    fun sharedReaderUsesExpenseAuthorityAndCannotStartConversion() = runTest {
        val events = mutableListOf<String>()
        val delegate = FakeApiService(mutableListOf(), 0)
        val api = object : ApiService by delegate {
            override suspend fun expenseFx(id: Long): BackgroundTaskDto? {
                events += "expense:$id"
                return BackgroundTaskDto("fx-$id", "expense_fx", "failed", createdAt = "2026-09-12T00:00:00Z", sourceExpenseId = id)
            }
            override suspend fun getBackgroundTask(publicId: String): BackgroundTaskDto = error("initiator-only endpoint")
            override suspend fun retryExpenseFx(id: Long, request: ExpenseStateTokenRequest): BackgroundTaskDto = error("reader cannot write")
        }
        val repository = expenseRepositoryFixture(expenseDao = FakeExpenseDao(), binding = testServerSessionBinding(
            apiClient = object : ApiServiceFactory {
                override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
            }, settingsStore = boundSettingsStore(role = "viewer"),
            tokenStore = TestSessionFixture().apply { saveToken("session-token") }), deviceNameProvider = { "Test" })
        val binding = requireNotNull(repository.captureDeferredLedgerBinding())
        assertEquals(9, repository.fetchExpenseFx(binding, 9).getOrThrow()?.sourceExpenseId?.toInt())
        val expense = delegate.expense(9).copy(status = "pending").toDomain()
        assertTrue(repository.retryExpenseFx(binding, expense).isFailure)
        assertEquals(listOf("expense:9"), events)
        assertTrue(repository.fetchExpenseFx(binding.copy(ledgerId = "other"), 9).isFailure)
        assertEquals(1, events.size)
    }

    @Test
    fun explicitReviewPublishesLatestPendingRevisionForOfflineReopen() = runTest {
        val dao = FakeExpenseDao()
        val base = FakeApiService(mutableListOf(), 0)
        val fresh = base.expense(9).copy(id = 9, status = "pending", rowVersion = 2,
            originalCurrency = "USD", originalAmountMinor = 1000, originalAmount = "10.00",
            amountCents = 7000, homeAmountCents = 7000, fxStatus = "ready", fxRate = "7", fxRateDate = "2026-09-11")
        val api = object : ApiService by base {
            override suspend fun expense(id: Long) = fresh
        }
        val repository = expenseRepositoryFixture(dao, testServerSessionBinding(
            apiClient = object : ApiServiceFactory {
                override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
            }, settingsStore = boundSettingsStore(), tokenStore = TestSessionFixture().apply { saveToken("session-token") }),
            deviceNameProvider = { "Test" })
        val binding = requireNotNull(repository.captureDeferredLedgerBinding())
        dao.upsertByServerIdForLedger(binding.ledgerId, fresh.copy(rowVersion = 1, amountCents = null,
            homeAmountCents = null, fxStatus = "pending").toEntity(binding.ledgerId))
        val reviewed = repository.fetchExpenseForFxReview(binding, 9).getOrThrow()
        val cached = repository.fetchExpenseFromLocalCache(9).getOrThrow()
        assertEquals(2L, reviewed.rowVersion)
        assertEquals(reviewed.rowVersion, cached.rowVersion)
        assertEquals(7000L, cached.homeAmountCents)
        assertEquals("2026-09-11", cached.fxRateDate)
        assertEquals("pending", cached.status)
    }

    @Test
    fun cachedPendingBillKeepsOriginalMoneyAndDoesNotInventTaskState() = runTest {
        val dao = FakeExpenseDao()
        val api = FakeApiService(mutableListOf(), 0)
        val repository = expenseRepositoryFixture(expenseDao = dao, binding = testServerSessionBinding(
            apiClient = FakeApiServiceFactory(api), settingsStore = boundSettingsStore(role = "member"),
            tokenStore = TestSessionFixture().apply { saveToken("session-token") }), deviceNameProvider = { "Test" })
        val ledger = requireNotNull(repository.captureDeferredLedgerBinding()).ledgerId
        val pending = api.expense(9).copy(id = 9, status = "pending", amountCents = null, homeAmountCents = null,
            originalCurrency = "USD", originalAmountMinor = 1000, originalAmount = "10.00", fxStatus = "pending")
        dao.upsertByServerIdForLedger(ledger, pending.toEntity(ledger))
        val cached = repository.fetchExpenseFromLocalCache(9).getOrThrow()
        assertEquals("pending", cached.status)
        assertEquals(1000L, cached.originalAmountMinor)
        assertEquals("USD", cached.originalCurrencyCodeRaw)
        assertNull(cached.fxTask)
        assertNull(cached.amountCents)
    }
}
