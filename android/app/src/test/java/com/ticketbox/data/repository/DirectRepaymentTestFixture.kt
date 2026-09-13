package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtRepaymentReceiptDto
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import java.io.IOException
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.flow.first
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response

internal class DirectRepaymentTestFixture(role: String = "owner") {
    val session = TestSessionFixture().apply {
        saveToken("synthetic-session")
        if (role != "owner") switchLedgerForFixture("owner", "测试账本", role)
    }
    val api = RepaymentResponseLossProbe()
    val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, session)
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val debt = api.current.toDomain()
    val dao = FakePendingMutationDao()
    val adapters = OutboxAdapterGraph()
    val clock: Clock = Clock.fixed(Instant.parse("2026-09-30T15:59:00Z"), ZoneOffset.UTC)
    val publishedDepths = mutableListOf<Int>()
    val outbox = newOutbox(clock)
    val repository = newRepository(outbox, clock)

    fun newOutbox(at: Clock) = OutboxRepository(dao, at, onRowsDeleted = {},
        bindingProvider = { provider.currentSession().toOutboxBinding() },
        onEnqueued = { publishedDepths += dao.rows.size })

    fun newRepository(outbox: OutboxRepository, at: Clock) = DebtWriteRepository(provider, outbox,
        adapters.debtAdjustmentAdapter, adapters.debtRepaymentAdapter, at)

    fun engine(outbox: OutboxRepository = this.outbox, at: Clock = clock) = OutboxDrainEngine(outbox,
        listOf(RecordDebtRepaymentDispatcher({ api }, adapters.debtRepaymentAdapter, adapters.debtRepaymentReceiptAdapter)),
        maxAttempts = 1, now = at::millis)

    suspend fun save(amount: Long = 10_000) = repository.saveRepayment(binding, debt, amount)
    suspend fun pending(repository: DebtWriteRepository = this.repository) =
        repository.observeWrites(binding, debt.publicId).first().single()
}

internal data class OriginalRepaymentCall(val target: String, val request: RepaymentCreateRequestDto, val key: String)

internal class RepaymentResponseLossProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    val calls = mutableListOf<OriginalRepaymentCall>()
    val facts = mutableMapOf<String, Pair<RepaymentCreateRequestDto, DebtRepaymentReceiptDto>>()
    var loseResponse = true
    var refusal: Pair<Int, String>? = null
    var receiptTransform: (DebtRepaymentReceiptDto) -> DebtRepaymentReceiptDto = { it }
    var current = DebtDto(
        publicId = "d1", ledgerId = "owner", direction = "i_owe", counterpartyType = "external",
        counterpartyLabel = "Bank", principalAmountCents = 50_000L, remainingAmountCents = 50_000L,
        paidAmountCents = 0L, status = "open", sourceType = "manual", homeCurrencyCode = "CNY",
        createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 1L,
    )

    override suspend fun debt(publicId: String): DebtDto = current

    override suspend fun recordDebtRepayment(publicId: String, request: RepaymentCreateRequestDto,
        idempotencyKey: String?): DebtRepaymentReceiptDto {
        val key = requireNotNull(idempotencyKey)
        calls += OriginalRepaymentCall(publicId, request, key)
        refusal?.let { (status, code) -> throw repaymentRefusal(status, code) }
        facts[key]?.let { (original, receipt) ->
            check(request == original)
            return receiptTransform(receipt)
        }
        if (request.expectedRowVersion != current.rowVersion) throw repaymentRefusal(409, "state_conflict")
        current = current.copy(remainingAmountCents = current.remainingAmountCents - request.amountCents,
            paidAmountCents = current.paidAmountCents + request.amountCents, rowVersion = current.rowVersion + 1L)
        val receipt = DebtRepaymentReceiptDto(publicId, "repayment-original", current.rowVersion, current.homeCurrencyCode)
        facts[key] = request to receipt
        if (loseResponse) throw IOException("Synthetic lost response after repayment commit")
        return receiptTransform(receipt)
    }
}

private fun repaymentRefusal(status: Int, code: String) = HttpException(Response.error<DebtRepaymentReceiptDto>(status,
    """{"error":"$code","message":"原还款尚未确认"}""".toResponseBody("application/json".toMediaType())))
