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
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentFactListDto
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
import kotlinx.coroutines.flow.flowOf

/** Disk Room and production graph; session and remote IO are synthetic. No real account or financial data. */
internal class DebtAdjustmentConnectedFixture(private val context: Context) {
    private val name = "debt-adjustment-continuity.db"
    private var database: AppDatabase? = null
    private val clock: Clock = Clock.fixed(Instant.parse("2026-09-30T15:30:00Z"), ZoneOffset.UTC)
    val network = DebtAdjustmentConnectedNetwork()
    private val adapters = OutboxAdapterGraph()
    private val session = debtAdjustmentConnectedSession()
    lateinit var outbox: OutboxRepository


    fun reopen(): RepositoryGraph {
        database?.close()
        val db = Room.databaseBuilder(context, AppDatabase::class.java, name).build().also { database = it }
        outbox = OutboxRepository(db.pendingMutationDao(), clock, bindingProvider = { session.toOutboxBinding() })
        val sessions = debtAdjustmentProxy<LocalSessionStore> { method -> when (method) {
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
            debtAdjustmentProxy<TicketboxSettingsStore> { error("Unexpected settings: $it") },
            sessions, credentials, ApiServiceProvider(factory, sessions, credentials), RepositoryGraphOutbox(outbox, adapters)))
    }

    fun stored(): List<Map<String, String?>> = requireNotNull(database).openHelper.readableDatabase
        .query("SELECT * FROM pending_mutations ORDER BY id").use { cursor -> buildList {
            while (cursor.moveToNext()) add(cursor.columnNames.mapIndexed { index, column -> column to cursor.getString(index) }.toMap())
        } }

    suspend fun drain(maxAttempts: Int = 10) = OutboxDrainEngine(outbox,
        listOf(RecordDebtAdjustmentDispatcher({ network.service }, adapters.debtAdjustmentAdapter)),
        maxAttempts = maxAttempts, now = clock::millis).drainOnce()

    fun close() { database?.close(); context.deleteDatabase(name) }
}

internal class DebtAdjustmentConnectedNetwork {
    var current = DebtDto(
        publicId = "debt-original", ledgerId = "debt-adjustment-ledger", direction = "i_owe",
        counterpartyType = "external", counterpartyLabel = "原借款对象", principalAmountCents = 50_000,
        remainingAmountCents = 50_000, paidAmountCents = 0, status = "open", sourceType = "manual",
        homeCurrencyCode = "CNY", createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 2,
    )
    var failReads = false
    var loseResponse = true
    val calls = mutableListOf<Pair<DebtAdjustmentCreateRequestDto, String>>()
    val results = mutableMapOf<String, DebtDto>()
    val service = object : ApiService by debtAdjustmentProxy<ApiService>({ error("Unexpected remote method: $it") }) {
        override suspend fun debt(publicId: String): DebtDto {
            check(publicId == current.publicId)
            if (failReads) throw IOException("Synthetic unavailable debt read")
            return current
        }

        override suspend fun debtRepayments(publicId: String, page: Int) =
            RepaymentFactListDto(publicId, "CNY", emptyList(), page, 20, 0)

        override suspend fun recordDebtAdjustment(publicId: String, request: DebtAdjustmentCreateRequestDto,
            idempotencyKey: String?): DebtDto {
            check(publicId == current.publicId)
            calls += request to requireNotNull(idempotencyKey)
            val response = results.getOrPut(idempotencyKey) {
                check(request.expectedRowVersion == current.rowVersion)
                current.copy(remainingAmountCents = current.remainingAmountCents + request.amountCents,
                    rowVersion = current.rowVersion + 1).also { current = it }
            }
            if (loseResponse) throw IOException("Synthetic lost response after commit")
            return response
        }
    }
}

private fun debtAdjustmentConnectedSession() = LocalSessionRecord(
    sessionGeneration = "income-session", bindingRevision = "income-binding",
    serverId = "40000000-0000-4000-8000-000000000001", dataGeneration = "40000000-0000-4000-8000-000000000002",
    serverUrl = "https://debt-adjustment.example.test", credential = StoredSessionToken(token = "synthetic-session"),
    identity = LocalSessionIdentity(accountPublicId = "40000000-0000-4000-8000-000000000003",
        devicePublicId = "40000000-0000-4000-8000-000000000004", accountName = "测试成员", ledgerId = "debt-adjustment-ledger",
        ledgerName = "测试账本", deviceName = "测试设备", role = "owner", boundAt = "2026-09-30T15:30:00Z"),
)

private inline fun <reified T> debtAdjustmentProxy(crossinline answer: (String) -> Any?): T =
    Proxy.newProxyInstance(T::class.java.classLoader, arrayOf(T::class.java)) { _, method, _ -> answer(method.name) } as T
