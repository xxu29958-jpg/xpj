package com.ticketbox.data.repository

import android.content.Context
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.RepositoryGraph
import com.ticketbox.RepositoryGraphDependencies
import com.ticketbox.RepositoryGraphOutbox
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionResponseDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseRevisionDto
import com.ticketbox.data.remote.dto.ExpenseRevisionPageDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseFinancialSummaryDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.remote.dto.BillSplitSentListResponseDto
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.StoredSessionToken
import java.io.IOException
import java.lang.reflect.Proxy
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.flow.MutableStateFlow
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException

/** Real disk Room and repository graph; only remote transport and session storage are synthetic. */
internal class ExpenseCorrectionConnectedFixture(private val context: Context) {
    private val name = "expense-correction-continuity.db"
    private var database: AppDatabase? = null
    private val clock = Clock.fixed(Instant.parse("2026-09-06T00:00:00Z"), ZoneOffset.UTC)
    private val session = MutableStateFlow(correctionSession())
    val network = CorrectionConnectedNetwork()
    private val adapters = OutboxAdapterGraph()
    lateinit var outbox: OutboxRepository
    lateinit var graph: RepositoryGraph
    var failCachePublication = false
    var confirmedCallbacks = 0
    var adviceCallbacks = 0
    var schedules = 0

    fun reopen(): RepositoryGraph {
        database?.close()
        val db = Room.databaseBuilder(context, AppDatabase::class.java, name).build().also { database = it }
        outbox = OutboxRepository(db.pendingMutationDao(), clock, bindingProvider = { session.value.toOutboxBinding() },
            onEnqueued = { check(stored().isNotEmpty()); schedules++ })
        val sessions = correctionProxy<LocalSessionStore> { method -> when (method) {
            "currentSession" -> session.value
            "observeSession" -> session
            "hasPersistedSessionState" -> true
            else -> error("Unexpected session method: $method")
        } }
        val credentials = SessionCredentialAdapter(sessions)
        val factory = object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = network.service
        }
        graph = RepositoryGraph(RepositoryGraphDependencies(db, ApiClient(),
            correctionProxy<TicketboxSettingsStore> { error("Unexpected settings: $it") }, sessions, credentials,
            ApiServiceProvider(factory, sessions, credentials), RepositoryGraphOutbox(outbox, adapters)))
        graph.expenseRepository.onConfirmedCommitted = { confirmedCallbacks++ }
        return graph
    }

    fun stored(): List<Map<String, String?>> = requireNotNull(database).openHelper.readableDatabase
        .query("SELECT * FROM pending_mutations ORDER BY id").use { cursor -> buildList {
            while (cursor.moveToNext()) add(cursor.columnNames.mapIndexed { index, column -> column to cursor.getString(index) }.toMap())
        } }

    suspend fun drain(maxAttempts: Int = 10) = OutboxDrainEngine(outbox,
        listOf(CorrectExpenseDispatcher(
            apiProvider = { network.service },
            payloadAdapter = adapters.correctionAdapter,
            cacheAuthoritativeExpense = { ledgerId, dto ->
                if (failCachePublication) throw IOException("Synthetic cache publication failure")
                requireNotNull(database).expenseDao().upsertByServerIdForLedger(ledgerId, dto.toEntity(ledgerId))
            },
            onConfirmedCommitted = { graph.expenseRepository.onConfirmedCommitted(it) },
        )), maxAttempts = maxAttempts, now = clock::millis)
        .also { it.onAdviceInputReplaySucceeded = { adviceCallbacks++ } }.drainOnce()

    fun role(value: String) { session.value = session.value.copy(identity = session.value.identity.copy(role = value)) }
    fun switchLedger() { session.value = session.value.copy(bindingRevision = "another-binding",
        identity = session.value.identity.copy(ledgerId = "another-ledger")) }
    fun close() { database?.close(); context.deleteDatabase(name) }
}

/** Response-loss model deduplicates by the actual original key and full request; not a PostgreSQL substitute. */
internal class CorrectionConnectedNetwork {
    var current = correctionExpense()
    var failReads = false
    var loseResponse = true
    var refusalCode: String? = null
    val calls = mutableListOf<Pair<ExpenseCorrectionRequestDto, String>>()
    val results = mutableMapOf<String, ExpenseCorrectionResponseDto>()
    val service = object : ApiService by correctionProxy<ApiService>({ throw IOException("Synthetic unavailable $it") }) {
        override suspend fun expense(id: Long): ExpenseDto { readable(); return current }
        override suspend fun categories() = CategoriesDto(listOf("餐饮", "购物"))
        override suspend fun ledgerMembers(ledgerId: String) = LedgerMemberListResponseDto(emptyList())
        override suspend fun listBillSplitSent() = BillSplitSentListResponseDto(emptyList())
        override suspend fun expenseItems(id: Long): ExpenseItemsResponseDto {
            readable()
            return ExpenseItemsResponseDto(id, current.rowVersion, current.amountCents, null, null, items = emptyList())
        }
        override suspend fun expenseSplits(id: Long): ExpenseSplitsResponseDto {
            readable()
            return ExpenseSplitsResponseDto(id, current.rowVersion, current.amountCents, null, null, emptyList())
        }
        override suspend fun expenseRevisions(id: Long, page: Int, pageSize: Int, snapshotRevision: Long?): ExpenseRevisionPageDto {
            readable()
            return ExpenseRevisionPageDto(results.values.map { it.revision }, page, pageSize, results.size, current.factRevision)
        }
        override suspend fun expenseFactBundle(id: Long): ExpenseFactBundleDto {
            readable()
            val amount = requireNotNull(current.originalAmountMinor)
            return ExpenseFactBundleDto(current, ExpenseFinancialSummaryDto(amount, amount, amount, 0, amount,
                amount, 0, ExpenseLineageStatusDto.Confirmed), emptyList())
        }
        override suspend fun correctExpense(id: String, request: ExpenseCorrectionRequestDto, idempotencyKey: String?): ExpenseCorrectionResponseDto {
            check(id == current.id.toString())
            val key = requireNotNull(idempotencyKey)
            calls += request to key
            refusalCode?.let { code ->
                throw HttpException(retrofit2.Response.error<ExpenseCorrectionResponseDto>(409,
                    """{"error":"$code","message":"private transport detail"}"""
                        .toResponseBody("application/json".toMediaType())))
            }
            val response = results[key] ?: run {
                check(request.expectedRowVersion == current.rowVersion)
                current = current.copy(merchant = request.merchant ?: current.merchant,
                    originalAmountMinor = request.originalAmountMinor ?: current.originalAmountMinor,
                    amountCents = request.originalAmountMinor ?: current.amountCents, rowVersion = current.rowVersion + 1,
                    factRevision = current.factRevision + 1)
                ExpenseCorrectionResponseDto(current, ExpenseRevisionDto("correction-1", current.factRevision, "correction",
                    request.reason, listOf("original_amount_minor"), null, emptyMap(), "家庭成员", "手机", "2026-09-06T00:00:00Z"))
                    .also { results[key] = it }
            }
            check(calls.first { it.second == key }.first == request) { "Replay mutated the original body" }
            if (loseResponse) throw IOException("Synthetic committed response loss")
            return response
        }
    }
    private fun readable() { if (failReads) throw IOException("Synthetic failed fact read") }
}

private fun correctionExpense() = ExpenseDto(id = 42, publicId = "expense-42", amountCents = 1000,
    homeCurrency = "CNY", originalCurrency = "CNY", originalCurrencyCode = "CNY", originalAmountMinor = 1000,
    merchant = "家庭午餐", category = "餐饮", note = null, source = "manual", imagePath = null, thumbnailPath = null,
    imageHash = null, rawText = null, confidence = null, duplicateStatus = "none", duplicateOfId = null,
    duplicateReason = null, tags = null, valueScore = null, regretScore = null, status = "confirmed", expenseTime = null,
    createdAt = "2026-09-06T00:00:00Z", updatedAt = "2026-09-06T00:00:00Z", rowVersion = 7, factRevision = 3,
    confirmedAt = "2026-09-06T00:00:00Z", rejectedAt = null)

private fun correctionSession() = LocalSessionRecord(sessionGeneration = "correction-session", bindingRevision = "correction-binding",
    serverId = "60000000-0000-4000-8000-000000000001", dataGeneration = "60000000-0000-4000-8000-000000000002",
    serverUrl = "https://correction.example.test", credential = StoredSessionToken(token = "synthetic-session"),
    identity = LocalSessionIdentity(accountPublicId = "60000000-0000-4000-8000-000000000003",
        devicePublicId = "60000000-0000-4000-8000-000000000004", accountName = "家庭成员", ledgerId = "correction-ledger",
        ledgerName = "家庭账本", deviceName = "测试手机", role = "member", boundAt = "2026-09-06T00:00:00Z"))

private inline fun <reified T> correctionProxy(crossinline answer: (String) -> Any?): T =
    Proxy.newProxyInstance(T::class.java.classLoader, arrayOf(T::class.java)) { _, method, _ -> answer(method.name) } as T
