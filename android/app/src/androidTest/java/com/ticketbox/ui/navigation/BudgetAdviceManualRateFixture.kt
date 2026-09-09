package com.ticketbox.ui.navigation

import android.content.Context
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.BudgetAdviceInputsDto
import com.ticketbox.data.remote.dto.BudgetAdviseRequestDto
import com.ticketbox.data.remote.dto.BudgetAdviseResponseDto
import com.ticketbox.data.remote.dto.DiscretionaryResponseDto
import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.data.remote.dto.ExchangeRateListDto
import com.ticketbox.data.remote.dto.ExchangeRateRequestDto
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.data.repository.ApiServiceProvider
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.LedgerRequestGuard
import com.ticketbox.data.repository.ManualExchangeRateDispatcher
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.toOutboxBinding
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.StoredSessionToken
import java.io.IOException
import java.lang.reflect.Proxy
import java.time.YearMonth
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first

/** Reuses the real route dependency graph; only transport/session storage is synthetic. */
internal class BudgetAdviceManualRateFixture(private val context: Context) : AutoCloseable {
    private val base = DataQualityConnectedHarness()
    private val name = "budget-advice-rate-${UUID.randomUUID()}.db"
    private var database: AppDatabase? = null
    val adapters = OutboxAdapterGraph()
    val originalMonth = YearMonth.now().minusMonths(1).toString()
    val rateDate = "$originalMonth-07"
    val request = ExchangeRateRequestDto("CNY", "JPY", rateDate, "20", "manual", 0)
    val inputReads = CopyOnWriteArrayList<Pair<String, String?>>()
    val writes = CopyOnWriteArrayList<Pair<ExchangeRateRequestDto, String>>()
    val adviceCalls = CopyOnWriteArrayList<BudgetAdviseRequestDto>()
    private val receipts = ConcurrentHashMap<String, ExchangeRateDto>()
    @Volatile var latest: ExchangeRateDto? = null
    @Volatile var loseAck = false
    @Volatile var runtimeHome = "JPY"
    private val session = MutableStateFlow(LocalSessionRecord(sessionGeneration = "rate-session", bindingRevision = "rate-binding",
        serverId = "3f6f1f2c-0000-4000-8000-000000000001", dataGeneration = "3f6f1f2c-0000-4000-8000-000000000002",
        serverUrl = "https://rates.example.test", credential = StoredSessionToken("synthetic-rate-token"),
        identity = LocalSessionIdentity(accountPublicId = "3f6f1f2c-0000-4000-8000-000000000003",
            devicePublicId = "3f6f1f2c-0000-4000-8000-000000000004", accountName = "QA", ledgerId = "rate-ledger",
            ledgerName = "Rate Ledger", deviceName = "QA Device", role = "owner", boundAt = "2026-01-01T00:00:00Z")))
    private val sessions = rateProxy<LocalSessionStore> { name -> when (name) {
        "currentSession" -> session.value
        "observeSession" -> session
        "hasPersistedSessionState" -> true
        else -> error("Unexpected session call: $name")
    } }
    private val api = object : ApiService by rateProxy<ApiService>({ error("Unexpected API call: $it") }) {
        override suspend fun budgetAdviceInputs(month: String, timezone: String?, homeCurrencyCode: String?): BudgetAdviceInputsDto {
            inputReads += month to homeCurrencyCode
            val home = homeCurrencyCode ?: runtimeHome
            val missing = latest == null && home == "JPY"
            return BudgetAdviceInputsDto(month, home,
                DiscretionaryResponseDto(10000, 1000, if (missing) null else 2000, 0, 0, if (missing) null else 7000),
                if (missing) listOf(MissingExchangeRateDto("CNY", "JPY", rateDate)) else emptyList())
        }
        override suspend fun exchangeRates(currencyCode: String?, homeCurrencyCode: String?, rateDate: String?, limit: Int) =
            ExchangeRateListDto(listOfNotNull(latest).filter { (currencyCode == null || it.currencyCode == currencyCode) &&
                (homeCurrencyCode == null || it.homeCurrencyCode == homeCurrencyCode) && (rateDate == null || it.rateDate == rateDate) })
        override suspend fun saveExchangeRate(currencyCode: String, rateDate: String,
            request: ExchangeRateRequestDto, idempotencyKey: String): ExchangeRateDto {
            check(currencyCode == request.currencyCode && rateDate == request.rateDate)
            writes += request to idempotencyKey
            val receipt = receipts.getOrPut(idempotencyKey) {
                ExchangeRateDto("original-rate", request.currencyCode, request.homeCurrencyCode, request.rateDate,
                    request.rateToHome, "manual", "2026-09-09T00:00:00Z", "2026-09-09T00:00:00Z",
                    request.expectedRowVersion + 1).also { latest = it }
            }
            if (loseAck) throw IOException("Synthetic lost acknowledgement")
            return receipt
        }
        override suspend fun budgetAdvise(request: BudgetAdviseRequestDto): BudgetAdviseResponseDto {
            adviceCalls += request
            return BudgetAdviseResponseDto(null, request.homeCurrencyCode, "empty", "ai_advisor_provider_empty")
        }
    }
    private val provider = ApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, sessions, SessionCredentialAdapter(sessions))
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    lateinit var outbox: OutboxRepository
    lateinit var repository: BudgetRepository
    val screenFactory get() = MainScreenFactory(base.screenFactory.repositories.copy(
        budgetRepository = repository, outboxRepository = outbox), base.screenFactory.viewModelFactories)

    init { reopen() }

    fun reopen() {
        database?.close()
        val db = Room.databaseBuilder(context, AppDatabase::class.java, name).build().also { database = it }
        outbox = OutboxRepository(dao = db.pendingMutationDao(), onRowsDeleted = {}, bindingProvider = { session.value.toOutboxBinding() })
        repository = BudgetRepository(provider, outbox, adapters.budgetSaveAdapter, adapters.budgetReceiptAdapter,
            adapters.manualRateAdapter, adapters.manualRateReceiptAdapter)
    }

    fun switchBinding() {
        session.value = session.value.copy(bindingRevision = "rate-replacement",
            identity = session.value.identity.copy(ledgerId = "another-rate-ledger", ledgerName = "Other Ledger"))
    }

    suspend fun rows() = requireNotNull(database).pendingMutationDao().allRows()
    suspend fun pending(id: Long) = repository.observeRates(binding).first().single { it.row.id == id }
    suspend fun drain() = OutboxDrainEngine(outbox, listOf(ManualExchangeRateDispatcher(
        { api }, adapters.manualRateAdapter, adapters.manualRateReceiptAdapter)), maxAttempts = 1).drainOnce()

    override fun close() { database?.close(); context.deleteDatabase(name); base.close() }
}

private inline fun <reified T> rateProxy(crossinline answer: (String) -> Any?): T = Proxy.newProxyInstance(
    T::class.java.classLoader, arrayOf(T::class.java),
) { _, method, _ -> when (method.name) {
    "toString" -> "BudgetAdviceRateProxy"
    "hashCode" -> 0
    "equals" -> false
    else -> answer(method.name)
} } as T
