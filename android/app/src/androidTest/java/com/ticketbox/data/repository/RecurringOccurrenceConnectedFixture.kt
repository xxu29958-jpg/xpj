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
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.StoredSessionToken
import java.io.IOException
import java.lang.reflect.Proxy
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.flow.flowOf

/** Production repository graph and disk Room. Only session and remote/cache observations are synthetic. */
internal class RecurringOccurrenceConnectedFixture(private val context: Context) {
    private val name = "recurring-occurrence-continuity.db"
    private var database: AppDatabase? = null
    private var clock: Clock = Clock.fixed(Instant.parse("2026-09-06T00:00:00Z"), ZoneOffset.UTC)
    val network = OccurrenceConnectedNetwork()
    private val adapters = OutboxAdapterGraph()
    private val session = occurrenceConnectedSession()
    lateinit var outbox: OutboxRepository
    val ledger: LedgerActions = object : LedgerActions by occurrenceProxy<LedgerActions>({ method, _ -> error("Unexpected ledger method: $method") }) {
        override fun observeConfirmedStream() = flowOf(listOf(occurrenceConnectedPayment()))
        override suspend fun syncConfirmed(month: String?, category: String?, tag: String?): Result<List<Expense>> =
            Result.success(listOf(occurrenceConnectedPayment().root))
    }

    fun reopen(): RepositoryGraph {
        database?.close()
        val db = Room.databaseBuilder(context, AppDatabase::class.java, name).build().also { database = it }
        outbox = OutboxRepository(db.pendingMutationDao(), clock, bindingProvider = { session.toOutboxBinding() })
        val sessions = occurrenceProxy<LocalSessionStore> { method, _ -> when (method) {
            "currentSession" -> session
            "observeSession" -> flowOf(session)
            "hasPersistedSessionState" -> true
            else -> error("Unexpected session method: $method")
        } }
        val credentials = SessionCredentialAdapter(sessions)
        val factory = object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = network.service
        }
        return RepositoryGraph(RepositoryGraphDependencies(db, ApiClient(),
            occurrenceProxy<TicketboxSettingsStore> { method, _ -> error("Unexpected settings: $method") },
            sessions, credentials, ApiServiceProvider(factory, sessions, credentials), RepositoryGraphOutbox(outbox, adapters)))
    }

    fun stored(): List<Map<String, String?>> = requireNotNull(database).openHelper.readableDatabase
        .query("SELECT * FROM pending_mutations ORDER BY id").use { cursor -> buildList {
            while (cursor.moveToNext()) add(cursor.columnNames.mapIndexed { index, column -> column to cursor.getString(index) }.toMap())
        } }

    suspend fun drain(maxAttempts: Int = 10) = OutboxDrainEngine(outbox,
        listOf(RecurringOccurrenceDispatcher({ network.service }, adapters.recurringOccurrenceAdapter)),
        maxAttempts = maxAttempts, now = clock::millis).drainOnce()

    fun advanceForRetry() { clock = Clock.offset(clock, Duration.ofMinutes(2)) }

    fun close() {
        database?.close()
        context.deleteDatabase(name)
    }
}

internal class OccurrenceConnectedNetwork {
    var current = RecurringOccurrenceDto("recurring-1", "2026-09", 7, 0, "unfulfilled", 10_000, 10_000, null, null, "2026-09-05")
    val calls = mutableListOf<Pair<RecurringOccurrencePaymentRequestDto, String>>()
    val results = mutableMapOf<String, RecurringOccurrenceDto>()
    var loseResponse = true
    var failReads = false
    val service = object : ApiService by occurrenceProxy<ApiService>({ method, _ -> error("Unexpected remote method: $method") }) {
        override suspend fun recurringOccurrence(publicId: String, month: String): RecurringOccurrenceDto {
            if (failReads) throw IOException("Synthetic unavailable period read")
            return current
        }
        override suspend fun setRecurringOccurrencePayment(
            publicId: String, month: String, request: RecurringOccurrencePaymentRequestDto, idempotencyKey: String,
        ): RecurringOccurrenceDto {
            check(publicId == current.seriesPublicId && month == current.period)
            calls += request to idempotencyKey
            val response = results.getOrPut(idempotencyKey) {
                check(request.expectedRowVersion == current.rowVersion)
                val linked = request.action == "link"
                current.copy(rowVersion = current.rowVersion + 1, state = if (linked) "fulfilled" else "unfulfilled",
                    reservedAmountCents = if (linked) 0 else 10_000, expensePublicId = request.expensePublicId,
                    paidAmountCents = if (linked) 12_345 else null, nextDueDate = if (linked) "2026-10-05" else "2026-09-05",
                    expenseId = if (linked) 1 else null)
                    .also { current = it }
            }
            if (loseResponse) throw IOException("Synthetic lost response after acceptance")
            return response
        }
    }
}

internal fun occurrenceConnectedItem() = RecurringItem(
    publicId = "recurring-1", ledgerId = "recurring-ledger", merchant = "房租", merchantKey = "房租", frequency = "monthly",
    baselineAmountCents = 10_000, lastAmountCents = 10_000, occurrenceCount = 0, lastSeenAt = null,
    nextExpectedDate = "2026-09-05", status = "active", confidence = null, source = "manual", anomalyStatus = "none",
    currentMonthAmountCents = null, historicalAverageAmountCents = null, amountDeltaPercent = null,
    createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 7, pausedAt = null,
    archivedAt = null, nextDueDate = "2026-09-05",
)

private fun occurrenceConnectedPayment() = ConfirmedStreamItem.ExpenseRow("2026-09-05", 12_345,
    Expense(id = 1, publicId = "payment-1", amountCents = 12_345, merchant = "房租付款", category = "居住", note = "本期完整付款",
        source = "manual", imagePath = null, thumbnailPath = null, imageHash = null, rawText = null, confidence = null,
        duplicateStatus = "", duplicateOfId = null, duplicateReason = null, tags = null, valueScore = null, regretScore = null,
        status = "confirmed", expenseTime = "2026-09-05T08:00:00Z", createdAt = "2026-09-05T08:00:00Z",
        updatedAt = "2026-09-05T08:00:00Z", rowVersion = 3, confirmedAt = "2026-09-05T08:00:00Z", rejectedAt = null),
    ExpenseLineageStatus.Confirmed, 12_345)

private fun occurrenceConnectedSession() = LocalSessionRecord(
    sessionGeneration = "occurrence-session", bindingRevision = "occurrence-binding",
    serverId = "30000000-0000-4000-8000-000000000001", dataGeneration = "30000000-0000-4000-8000-000000000002",
    serverUrl = "https://recurring.example.test", credential = StoredSessionToken(token = "synthetic-session"),
    identity = LocalSessionIdentity(accountPublicId = "30000000-0000-4000-8000-000000000003",
        devicePublicId = "30000000-0000-4000-8000-000000000004", accountName = "测试成员", ledgerId = "recurring-ledger",
        ledgerName = "测试账本", deviceName = "测试设备", role = "owner", boundAt = "2026-09-06T00:00:00Z"),
)

private inline fun <reified T> occurrenceProxy(crossinline answer: (String, Array<out Any?>) -> Any?): T =
    Proxy.newProxyInstance(T::class.java.classLoader, arrayOf(T::class.java)) { _, method, arguments ->
        answer(method.name, arguments.orEmpty())
    } as T
