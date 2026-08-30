package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionResponseDto
import com.ticketbox.data.remote.dto.ExpenseRevisionDto
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseCorrectionOutcome
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseSplitDraft
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

internal class ExpenseCorrectionRepositoryTest : ExpensePendingRepositoryOutboxTestBase() {

    @Test
    fun `queued correction projects home amount only when the edited currency is the known home currency`() {
        val baseline = baselineExpense().copy(
            amountCents = 1_000L,
            homeAmountCents = 1_000L,
            homeCurrencyCode = "CNY",
            originalCurrencyCode = CurrencyCode.CNY,
            originalCurrencyCodeRaw = "CNY",
            originalAmountMinor = 1_000L,
        )

        val projected = baseline.projectCorrection(
            ExpenseCorrectionDraft(
                reason = "金额应更高",
                originalCurrencyCode = CurrencyCode.CNY,
                originalAmountMinor = 1_200L,
            ),
        )

        assertEquals(1_200L, projected.amountCents)
        assertEquals(1_200L, projected.homeAmountCents)
    }

    @Test
    fun `queued foreign-currency amount correction reuses the immutable rate snapshot`() {
        val baseline = baselineExpense().copy(
            amountCents = 6_000L,
            homeAmountCents = 6_000L,
            homeCurrencyCode = "CNY",
            originalCurrencyCode = CurrencyCode.JPY,
            originalCurrencyCodeRaw = "JPY",
            originalAmountMinor = 1_200L,
            exchangeRateToCny = "0.05",
            fxStatus = "ready",
        )

        val projected = baseline.projectCorrection(
            ExpenseCorrectionDraft(
                reason = "修正原币金额",
                originalCurrencyCode = CurrencyCode.JPY,
                originalAmountMinor = 1_300L,
            ),
        )

        assertEquals(6_500L, projected.amountCents)
        assertEquals(6_500L, projected.homeAmountCents)
        assertEquals(1_300L, projected.originalAmountMinor)
    }

    @Test
    fun `queued foreign-currency time correction keeps the prior authoritative FX snapshot`() {
        val baseline = baselineExpense().copy(
            amountCents = 6_000L,
            homeAmountCents = 6_000L,
            homeCurrencyCode = "CNY",
            originalCurrencyCode = CurrencyCode.JPY,
            originalCurrencyCodeRaw = "JPY",
            originalAmountMinor = 1_200L,
            exchangeRateToCny = "0.05",
            fxStatus = "ready",
        )

        val projected = baseline.projectCorrection(
            ExpenseCorrectionDraft(
                reason = "日期和金额都需修正",
                originalCurrencyCode = CurrencyCode.JPY,
                originalAmountMinor = 1_300L,
                expenseTime = "2026-08-31T08:00:00Z",
                expenseTimeChanged = true,
            ),
        )

        assertEquals(6_000L, projected.amountCents)
        assertEquals(6_000L, projected.homeAmountCents)
        assertEquals(CurrencyCode.JPY, projected.originalCurrencyCode)
        assertEquals("JPY", projected.originalCurrencyCodeRaw)
        assertEquals(1_200L, projected.originalAmountMinor)
        assertEquals("0.05", projected.exchangeRateToCny)
        assertEquals("ready", projected.fxStatus)
        assertEquals(baseline.expenseTime, projected.expenseTime)
    }

    @Test
    fun `queued currency change keeps the prior authoritative FX snapshot until replay`() {
        val baseline = baselineExpense().copy(
            amountCents = 6_000L,
            homeAmountCents = 6_000L,
            homeCurrencyCode = "CNY",
            originalCurrencyCode = CurrencyCode.JPY,
            originalCurrencyCodeRaw = "JPY",
            originalAmountMinor = 1_200L,
            exchangeRateToCny = "0.05",
            exchangeRateDate = "2026-05-20",
            exchangeRateSource = "provider",
            fxStatus = "ready",
        )

        val projected = baseline.projectCorrection(
            ExpenseCorrectionDraft(
                reason = "币种应为美元",
                originalCurrencyCode = CurrencyCode.USD,
                originalAmountMinor = 1_300L,
            ),
        )

        assertEquals(6_000L, projected.amountCents)
        assertEquals(6_000L, projected.homeAmountCents)
        assertEquals(CurrencyCode.JPY, projected.originalCurrencyCode)
        assertEquals("JPY", projected.originalCurrencyCodeRaw)
        assertEquals(1_200L, projected.originalAmountMinor)
        assertEquals("0.05", projected.exchangeRateToCny)
        assertEquals("2026-05-20", projected.exchangeRateDate)
        assertEquals("provider", projected.exchangeRateSource)
        assertEquals("ready", projected.fxStatus)
    }

    @Test
    fun `queued amount correction does not project home money when the raw home currency is unsupported`() {
        val baseline = baselineExpense().copy(
            amountCents = 1_000L,
            homeAmountCents = 1_000L,
            homeCurrencyCode = "VND",
            originalCurrencyCode = CurrencyCode.CNY,
            originalCurrencyCodeRaw = "CNY",
            originalAmountMinor = 1_000L,
        )

        val projected = baseline.projectCorrection(
            ExpenseCorrectionDraft(
                reason = "金额应更高",
                originalCurrencyCode = CurrencyCode.CNY,
                originalAmountMinor = 1_200L,
            ),
        )

        assertEquals(1_000L, projected.amountCents)
        assertEquals(1_000L, projected.homeAmountCents)
    }

    @Test
    fun `queued composite amount and splits keeps the prior coherent money projection`() {
        val baseline = baselineExpense().copy(
            amountCents = 1_000L,
            homeAmountCents = 1_000L,
            homeCurrencyCode = "CNY",
            originalCurrencyCode = CurrencyCode.CNY,
            originalCurrencyCodeRaw = "CNY",
            originalAmountMinor = 1_000L,
        )

        val projected = baseline.projectCorrection(
            ExpenseCorrectionDraft(
                reason = "金额和分摊一起修正",
                originalCurrencyCode = CurrencyCode.CNY,
                originalAmountMinor = 1_200L,
                splits = listOf(ExpenseSplitDraft(memberId = 7L, amountCents = 1_200L, note = null)),
            ),
        )

        assertEquals(1_000L, projected.amountCents)
        assertEquals(1_000L, projected.homeAmountCents)
        assertEquals(1_000L, projected.originalAmountMinor)
    }

    @Test
    fun `direct correction sends OCC and reason then caches authoritative fact revision`() = runTest {
        val dao = FakeExpenseDao()
        val responseExpense = successExpenseDto().copy(
            status = "confirmed",
            category = "购物",
            rowVersion = 4L,
            factRevision = 2L,
            confirmedAt = "2026-05-20T12:30:00Z",
        )
        val api = CorrectionApiService(
            delegate = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0),
            response = ExpenseCorrectionResponseDto(
                expense = responseExpense,
                revision = revisionDto(),
            ),
        )
        val repo = buildCorrectionRepository(api = api, expenseDao = dao)
        val baseline = baselineExpense().copy(
            status = "confirmed",
            confirmedAt = "2026-05-20T12:30:00Z",
            rowVersion = 3L,
            factRevision = 1L,
        )

        val outcome = repo.correctExpenseAllowingOffline(
            expense = baseline,
            correction = ExpenseCorrectionDraft(reason = " 分类识别有误 ", category = "购物"),
        ).getOrThrow()

        val synced = assertIs<ExpenseCorrectionOutcome.Synced>(outcome)
        assertEquals(2L, synced.expense.factRevision)
        assertEquals(2L, synced.revision.revisionNumber)
        assertEquals(3L, api.request?.expectedRowVersion)
        assertEquals("分类识别有误", api.request?.reason)
        assertNotNull(api.idempotencyKey)
        val cached = assertNotNull(dao.findByServerId("owner", baseline.id))
        assertEquals(2L, cached.factRevision)
        assertEquals("购物", cached.category)
    }

    @Test
    fun `network loss queues same correction identity without forging a revision`() = runTest {
        val mutationDao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = mutationDao)
        val api = CorrectionApiService(
            delegate = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0),
            failure = IOException("offline"),
        )
        val repo = buildCorrectionRepository(api = api, outbox = outbox)
        val baseline = baselineExpense().copy(
            status = "confirmed",
            confirmedAt = "2026-05-20T12:30:00Z",
            rowVersion = 7L,
            factRevision = 3L,
        )

        val outcome = repo.correctExpenseAllowingOffline(
            expense = baseline,
            correction = ExpenseCorrectionDraft(reason = "补充原始备注", note = "公司午餐"),
        ).getOrThrow()

        val queued = assertIs<ExpenseCorrectionOutcome.Queued>(outcome)
        assertEquals("公司午餐", queued.expense.note)
        assertEquals(3L, queued.expense.factRevision, "queued intent must not invent a published revision")
        val row = mutationDao.rows.values.single()
        assertEquals(PendingMutationType.CorrectExpense.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(7L, row.expectedRowVersion)
        assertEquals(api.idempotencyKey, row.idempotencyKey)
        assertTrue(row.payload.contains("\"expected_row_version\":0"), row.payload)
        assertTrue(row.payload.contains("补充原始备注"), row.payload)
    }

    @Test
    fun `server success remains synced when Room publication needs a later refresh`() = runTest {
        val dao = FakeExpenseDao().apply {
            insertFailure = IllegalStateException("room unavailable")
        }
        val responseExpense = successExpenseDto().copy(
            status = "confirmed",
            category = "购物",
            rowVersion = 4L,
            factRevision = 2L,
            confirmedAt = "2026-05-20T12:30:00Z",
        )
        val api = CorrectionApiService(
            delegate = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0),
            response = ExpenseCorrectionResponseDto(
                expense = responseExpense,
                revision = revisionDto(),
            ),
        )
        val repo = buildCorrectionRepository(api = api, expenseDao = dao)
        val baseline = baselineExpense().copy(
            status = "confirmed",
            confirmedAt = "2026-05-20T12:30:00Z",
            rowVersion = 3L,
            factRevision = 1L,
        )

        val outcome = repo.correctExpenseAllowingOffline(
            expense = baseline,
            correction = ExpenseCorrectionDraft(reason = "修正分类", category = "购物"),
        ).getOrThrow()

        val synced = assertIs<ExpenseCorrectionOutcome.Synced>(outcome)
        assertEquals(2L, synced.expense.factRevision)
        assertTrue(synced.refreshPending)
    }

    private fun buildCorrectionRepository(
        api: ApiService,
        expenseDao: FakeExpenseDao = FakeExpenseDao(),
        outbox: OutboxRepository? = null,
    ): ExpenseRepository = ExpenseRepository(
        expenseDao = expenseDao,
        binding = testServerSessionBinding(
            apiClient = TestApiServiceFactory(api),
            settingsStore = seededSettingsStore(),
            tokenStore = seededTokenStore(),
        ),
        deviceNameProvider = { "Android Test" },
        offlineMutations = ExpenseOfflineMutationWiring(
            outbox = outbox,
            correctionAdapter = moshi().adapter(ExpenseCorrectionRequestDto::class.java),
        ),
    )

    private fun revisionDto(): ExpenseRevisionDto = ExpenseRevisionDto(
        publicId = "revision-public-id",
        revisionNumber = 2L,
        changeKind = "correction",
        reason = "分类识别有误",
        changedFields = listOf("category"),
        before = mapOf("category" to "餐饮"),
        after = mapOf("category" to "购物"),
        actorAccountName = "我",
        actorDeviceName = "Pixel",
        createdAt = "2026-05-20T13:00:00Z",
    )

    private class CorrectionApiService(
        private val delegate: ApiService,
        private val response: ExpenseCorrectionResponseDto? = null,
        private val failure: Throwable? = null,
    ) : ApiService by delegate {
        var request: ExpenseCorrectionRequestDto? = null
            private set
        var idempotencyKey: String? = null
            private set

        override suspend fun correctExpense(
            id: String,
            request: ExpenseCorrectionRequestDto,
            idempotencyKey: String?,
        ): ExpenseCorrectionResponseDto {
            this.request = request
            this.idempotencyKey = idempotencyKey
            failure?.let { throw it }
            return requireNotNull(response)
        }
    }
}
