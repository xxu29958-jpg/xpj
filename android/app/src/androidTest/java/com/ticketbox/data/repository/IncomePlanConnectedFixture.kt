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
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.data.remote.dto.IncomePlanListResponseDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.domain.model.DebtListLens
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

/** Disk Room and the real repository graph. Session, currency observation and remote transport are synthetic. */
internal class IncomePlanConnectedFixture(private val context: Context) {
    private val name = "income-plan-continuity.db"
    private var database: AppDatabase? = null
    private var clock: Clock = Clock.fixed(Instant.parse("2026-09-30T15:30:00Z"), ZoneOffset.UTC)
    val network = IncomeConnectedNetwork()
    private val adapters = OutboxAdapterGraph()
    private val session = incomeConnectedSession()
    lateinit var outbox: OutboxRepository
    val debts = object : DebtActions by incomeProxy<DebtActions>({ error("Unexpected debt method: $it") }) {
        override suspend fun listDebts(lens: DebtListLens) = Result.success(DebtListPage(emptyList(), "CNY"))
    }

    fun reopen(): RepositoryGraph {
        database?.close()
        val db = Room.databaseBuilder(context, AppDatabase::class.java, name).build().also { database = it }
        outbox = OutboxRepository(db.pendingMutationDao(), clock, bindingProvider = { session.toOutboxBinding() })
        val sessions = incomeProxy<LocalSessionStore> { method -> when (method) {
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
            incomeProxy<TicketboxSettingsStore> { error("Unexpected settings: $it") },
            sessions, credentials, ApiServiceProvider(factory, sessions, credentials), RepositoryGraphOutbox(outbox, adapters)))
    }

    fun stored(): List<Map<String, String?>> = requireNotNull(database).openHelper.readableDatabase
        .query("SELECT * FROM pending_mutations ORDER BY id").use { cursor -> buildList {
            while (cursor.moveToNext()) add(cursor.columnNames.mapIndexed { index, column -> column to cursor.getString(index) }.toMap())
        } }

    suspend fun drain(maxAttempts: Int = 10) = OutboxDrainEngine(outbox,
        listOf(UpdateIncomePlanDispatcher({ network.service }, adapters.incomePlanUpdateAdapter)),
        maxAttempts = maxAttempts, now = clock::millis).drainOnce()

    fun advanceToOctober() { clock = Clock.offset(clock, Duration.ofDays(1)); network.month = "2026-10" }

    fun close() { database?.close(); context.deleteDatabase(name) }
}

internal class IncomeConnectedNetwork {
    var current = IncomePlanDto("income-1", "九月工资计划", "salary", "monthly", null, 10_000, 1,
        "active", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z", 3, null)
    var month = "2026-09"
    var failReads = false
    var loseResponse = true
    val calls = mutableListOf<Pair<IncomePlanUpdateRequestDto, String>>()
    val results = mutableMapOf<String, IncomePlanDto>()
    val service = object : ApiService by incomeProxy<ApiService>({ error("Unexpected remote method: $it") }) {
        override suspend fun listIncomePlans(status: String): IncomePlanListResponseDto {
            if (failReads) throw IOException("Synthetic unavailable management read")
            return IncomePlanListResponseDto(if (status == "active") listOf(current) else emptyList(),
                current.amountCents, month, current.amountCents, 1, current.amountCents)
        }

        override suspend fun updateIncomePlan(publicId: String, request: IncomePlanUpdateRequestDto,
            idempotencyKey: String?): IncomePlanDto {
            check(publicId == current.publicId)
            calls += request to requireNotNull(idempotencyKey)
            val response = results.getOrPut(idempotencyKey) {
                check(request.expectedRowVersion == current.rowVersion)
                current.copy(amountCents = requireNotNull(request.amountCents), rowVersion = current.rowVersion + 1)
                    .also { current = it }
            }
            if (loseResponse) throw IOException("Synthetic lost response after commit")
            return response
        }
    }
}

private fun incomeConnectedSession() = LocalSessionRecord(
    sessionGeneration = "income-session", bindingRevision = "income-binding",
    serverId = "40000000-0000-4000-8000-000000000001", dataGeneration = "40000000-0000-4000-8000-000000000002",
    serverUrl = "https://income.example.test", credential = StoredSessionToken(token = "synthetic-session"),
    identity = LocalSessionIdentity(accountPublicId = "40000000-0000-4000-8000-000000000003",
        devicePublicId = "40000000-0000-4000-8000-000000000004", accountName = "测试成员", ledgerId = "income-ledger",
        ledgerName = "测试账本", deviceName = "测试设备", role = "owner", boundAt = "2026-09-30T15:30:00Z"),
)

private inline fun <reified T> incomeProxy(crossinline answer: (String) -> Any?): T =
    Proxy.newProxyInstance(T::class.java.classLoader, arrayOf(T::class.java)) { _, method, _ -> answer(method.name) } as T
