package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.domain.model.ExpenseItems
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException

/**
 * Shared setup/fixtures for the ``ExpensePendingRepositoryOutbox*`` test
 * classes (ADR-0038 PR-2g.x offline-fallback / outbox-queue contract).
 *
 * Extracted verbatim from the original
 * ``ExpensePendingRepositoryOutboxFallbackTest`` when that oversized
 * class was split into themed siblings; this is a pure redistribution,
 * so every builder/stub here is byte-identical to the pre-split version
 * (only ``private`` → ``protected`` so the themed subclasses can reach
 * them). Uniquely prefixed (``ExpensePendingRepositoryOutbox…``) so it
 * cannot collide with the sibling ``Merchant``/``Rule`` outbox-fallback
 * support that lives in the same package.
 *
 * The fakes themselves ([FakeApiService], [FakeExpenseDao],
 * [FakePendingMutationDao], [FakeTicketboxSettingsStore],
 * [FakeSessionTokenStore]) live in other same-package files and are
 * reused by name.
 */
internal abstract class ExpensePendingRepositoryOutboxTestBase {

    protected fun baselineExpense(updatedAt: String = "2026-05-20T12:00:05.000Z"): Expense = Expense(
        id = 42L,
        publicId = "test-public-id",
        amountCents = 12345L,
        merchant = "原商家",
        category = "餐饮",
        note = "",
        source = "Android截图",
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "pending",
        expenseTime = "2026-05-20T12:00:00Z",
        createdAt = "2026-05-20T12:00:00Z",
        updatedAt = updatedAt,
        rowVersion = 1L,
        confirmedAt = null,
        rejectedAt = null,
    )

    protected val draft = ExpenseDraft(
        amountCents = 12345L,
        originalAmountMinor = 12345L,
        originalCurrencyCode = CurrencyCode.CNY,
        merchant = "新商家",
        category = "餐饮",
        note = "",
        expenseTime = "2026-05-20T12:00:00Z",
        tags = null,
        valueScore = null,
        regretScore = null,
    )

    protected fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    protected fun seededSettingsStore(): FakeTicketboxSettingsStore =
        FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }

    protected fun seededTokenStore(): FakeSessionTokenStore =
        FakeSessionTokenStore().apply { saveToken("session-token") }

    protected class TestApiServiceFactory(private val service: ApiService) : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
    }

    protected fun buildRepository(
        api: ApiService,
        outbox: OutboxRepository? = null,
        adapter: com.squareup.moshi.JsonAdapter<ExpenseUpdateRequest>? = null,
        stateTokenAdapter: com.squareup.moshi.JsonAdapter<ExpenseStateTokenRequest>? = null,
    ): ExpenseRepository = ExpenseRepository(
        expenseDao = FakeExpenseDao(),
        apiClient = TestApiServiceFactory(api),
        settingsStore = seededSettingsStore(),
        tokenStore = seededTokenStore(),
        deviceNameProvider = { "Android Test" },
        outbox = outbox,
        patchExpenseAdapter = adapter,
        expenseStateTokenAdapter = stateTokenAdapter,
    )

    protected fun successExpenseDto(serverUpdatedAt: String = "2026-05-20T13:00:00.000Z"): ExpenseDto =
        ExpenseDto(
            id = 42L,
            publicId = "test-public-id",
            amountCents = 12345L,
            merchant = "新商家",
            category = "餐饮",
            note = "",
            source = "Android截图",
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = null,
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "pending",
            expenseTime = "2026-05-20T12:00:00Z",
            createdAt = "2026-05-20T12:00:00Z",
            updatedAt = serverUpdatedAt,
            rowVersion = 2L,
            confirmedAt = null,
            rejectedAt = null,
        )

    protected fun mismatchKnownItems(): ExpenseItems = ExpenseItems(
        expenseId = 42L,
        parentAmountCents = 12345L,
        itemsTotalAmountCents = 10000L,
        mismatchCents = 2345L,
        itemsSumStatus = "mismatch_known",
        items = emptyList(),
    )

    protected fun itemsCurrent(): ExpenseItems = ExpenseItems(
        expenseId = 42L,
        parentAmountCents = 12345L,
        itemsTotalAmountCents = 12345L,
        mismatchCents = 0L,
        itemsSumStatus = "matched",
        items = emptyList(),
    )

    protected val itemDrafts: List<ExpenseItemDraft> = listOf(
        ExpenseItemDraft(
            name = "咖啡",
            quantityText = null,
            unitPriceCents = null,
            amountCents = 2500L,
            category = null,
            rawText = null,
            confidence = null,
            kind = ExpenseItemKind.PRODUCT,
        ),
    )

    protected fun itemsRepo(api: ApiService, outbox: OutboxRepository): ExpenseRepository = ExpenseRepository(
        expenseDao = FakeExpenseDao(),
        apiClient = TestApiServiceFactory(api),
        settingsStore = seededSettingsStore(),
        tokenStore = seededTokenStore(),
        deviceNameProvider = { "Android Test" },
        outbox = outbox,
        replaceItemsAdapter = moshi().adapter(ExpenseItemReplaceRequestDto::class.java),
    )

    protected sealed interface ApiResult {
        data class Success(val dto: ExpenseDto) : ApiResult
        data class Throw(val exception: Throwable) : ApiResult
    }

    /**
     * Minimal ApiService stand-in: every method falls through to a
     * delegate that throws (via FakeApiService), but ``updateExpense``
     * is configurable per test (return a DTO or throw).
     */
    protected class ApiServiceStub(
        private val updateExpenseResult: ApiResult = ApiResult.Throw(
            IllegalStateException("updateExpense not configured"),
        ),
        // ADR-0042 Slice C: per-expense-id overrides so a fan-out test can mix
        // outcomes (id 1 → Success, id 2 → IOException, id 3 → 409) in one batch.
        // Falls back to ``updateExpenseResult`` for ids not in the map.
        private val updateExpenseResultById: Map<Long, ApiResult> = emptyMap(),
        private val confirmExpenseResult: ApiResult = ApiResult.Throw(
            IllegalStateException("confirmExpense not configured"),
        ),
        private val rejectExpenseResult: ApiResult = ApiResult.Throw(
            IllegalStateException("rejectExpense not configured"),
        ),
        private val markNotDuplicateResult: ApiResult = ApiResult.Throw(
            IllegalStateException("markNotDuplicate not configured"),
        ),
        private val retryOcrResult: ApiResult = ApiResult.Throw(
            IllegalStateException("retryOcr not configured"),
        ),
        // acknowledge returns ExpenseItemsResponseDto (not ExpenseDto), so
        // it can't reuse ApiResult; null exception = success.
        private val acknowledgeException: Throwable? = null,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        // ADR-0042: records the Idempotency-Key the repository supplied on each
        // direct attempt so tests can assert it matches the enqueued row's key.
        // Captured before the result is applied so the IOException path still
        // sees it. ``lastIdempotencyKey`` is the PATCH one (Slice B); the
        // per-op vars below cover the Slice D-1 state-machine mutations.
        var lastIdempotencyKey: String? = null
            private set
        // ADR-0042 Slice C: the body of the most recent updateExpense PATCH so
        // fan-out tests can assert the field-selective build (category-only must
        // not carry tags and vice-versa).
        var lastUpdateRequest: ExpenseUpdateRequest? = null
            private set
        var lastConfirmIdempotencyKey: String? = null
            private set
        var lastRejectIdempotencyKey: String? = null
            private set
        var lastMarkNotDuplicateIdempotencyKey: String? = null
            private set
        var lastRetryOcrIdempotencyKey: String? = null
            private set
        var lastAcknowledgeIdempotencyKey: String? = null
            private set

        override suspend fun updateExpense(
            id: Long,
            request: ExpenseUpdateRequest,
            idempotencyKey: String?,
        ): ExpenseDto {
            lastIdempotencyKey = idempotencyKey
            lastUpdateRequest = request
            return when (val r = updateExpenseResultById[id] ?: updateExpenseResult) {
                is ApiResult.Success -> r.dto
                is ApiResult.Throw -> throw r.exception
            }
        }

        override suspend fun confirmExpense(
            id: Long,
            request: ExpenseStateTokenRequest,
            idempotencyKey: String?,
        ): ExpenseDto {
            lastConfirmIdempotencyKey = idempotencyKey
            return when (val r = confirmExpenseResult) {
                is ApiResult.Success -> r.dto
                is ApiResult.Throw -> throw r.exception
            }
        }

        override suspend fun rejectExpense(
            id: Long,
            request: ExpenseStateTokenRequest,
            idempotencyKey: String?,
        ): ExpenseDto {
            lastRejectIdempotencyKey = idempotencyKey
            return when (val r = rejectExpenseResult) {
                is ApiResult.Success -> r.dto
                is ApiResult.Throw -> throw r.exception
            }
        }

        override suspend fun markNotDuplicate(
            id: Long,
            request: ExpenseStateTokenRequest,
            idempotencyKey: String?,
        ): ExpenseDto {
            lastMarkNotDuplicateIdempotencyKey = idempotencyKey
            return when (val r = markNotDuplicateResult) {
                is ApiResult.Success -> r.dto
                is ApiResult.Throw -> throw r.exception
            }
        }

        override suspend fun retryOcr(
            id: Long,
            request: ExpenseStateTokenRequest,
            idempotencyKey: String?,
        ): ExpenseDto {
            lastRetryOcrIdempotencyKey = idempotencyKey
            return when (val r = retryOcrResult) {
                is ApiResult.Success -> r.dto
                is ApiResult.Throw -> throw r.exception
            }
        }

        override suspend fun acknowledgeExpenseItemsMismatch(
            id: Long,
            request: ExpenseStateTokenRequest,
            idempotencyKey: String?,
        ): ExpenseItemsResponseDto {
            lastAcknowledgeIdempotencyKey = idempotencyKey
            acknowledgeException?.let { throw it }
            return ExpenseItemsResponseDto(
                expenseId = id,
                rowVersion = 1L,
                parentAmountCents = 12345L,
                itemsTotalAmountCents = 10000L,
                mismatchCents = 2345L,
                itemsSumStatus = "mismatch_acknowledged",
                items = emptyList(),
            )
        }
    }

    protected fun httpException(code: Int, body: String): HttpException {
        val raw = Response.Builder()
            .protocol(Protocol.HTTP_1_1)
            .request(Request.Builder().url("https://api.example.com/").build())
            .code(code)
            .message("test")
            .body(body.toResponseBody("application/json".toMediaTypeOrNull()))
            .build()
        return HttpException(retrofit2.Response.error<ExpenseDto>(body.toResponseBody("application/json".toMediaTypeOrNull()), raw))
    }
}
