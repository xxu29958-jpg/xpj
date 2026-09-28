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
import com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanListResponseDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.data.remote.dto.IncomeHistoryResponseDto
import com.ticketbox.data.remote.dto.IncomeRevisionDto
import com.ticketbox.data.remote.dto.IncomeDefinitionDto
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
    private var session = incomeConnectedSession()
    private val deniedReads = mutableMapOf<String, Int>()
    lateinit var outbox: OutboxRepository

    fun reopen(): RepositoryGraph {
        database?.close()
        val db = Room.databaseBuilder(context, AppDatabase::class.java, name).build().also { database = it }
        outbox = OutboxRepository(db.pendingMutationDao(), clock, onRowsDeleted = {}, bindingProvider = { session.toOutboxBinding() })
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
            object : TicketboxSettingsStore by incomeProxy<TicketboxSettingsStore>({ error("Unexpected settings: $it") }) {
                override fun snapshotReadAccessDenial(bindingKey: String, monthlyBindingKey: String) = deniedReads[bindingKey]
                override fun saveSnapshotReadAccessDenial(bindingKey: String, monthlyBindingKey: String, status: Int?) {
                    if (status == null) deniedReads.remove(bindingKey) else deniedReads[bindingKey] = status
                }
            },
            sessions, credentials, ApiServiceProvider(factory, sessions, credentials), RepositoryGraphOutbox(outbox, adapters)))
    }

    fun stored(): List<Map<String, String?>> = requireNotNull(database).openHelper.readableDatabase
        .query("SELECT * FROM pending_mutations ORDER BY id").use { cursor -> buildList {
            while (cursor.moveToNext()) add(cursor.columnNames.mapIndexed { index, column -> column to cursor.getString(index) }.toMap())
        } }

    suspend fun drain(maxAttempts: Int = 10) = OutboxDrainEngine(outbox,
        listOf(IncomePlanDispatcher(com.ticketbox.data.local.PendingMutationType.UpdateIncomePlan, { network.service },
            adapters.incomePlanSubmissionAdapter, adapters.incomePlanReceiptAdapter),
            IncomePlanDispatcher(com.ticketbox.data.local.PendingMutationType.CreateIncomePlan, { network.service },
                adapters.incomePlanSubmissionAdapter, adapters.incomePlanReceiptAdapter)),
        maxAttempts = maxAttempts, now = clock::millis).drainOnce()

    fun advanceToOctober() { clock = Clock.offset(clock, Duration.ofDays(1)); network.month = "2026-10" }

    fun changeAccount() {
        session = session.copy(sessionGeneration = "another-session", bindingRevision = "another-binding",
            identity = session.identity.copy(accountPublicId = "40000000-0000-4000-8000-000000000005"))
    }

    fun close() { database?.close(); context.deleteDatabase(name) }
}

internal class IncomeConnectedNetwork {
    var current = IncomePlanDto("income-1", "九月工资计划", "salary", "monthly", null, 10_000, 1,
        "active", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z", 3, null, homeCurrencyCode = "CNY")
    var month = "2026-09"
    var forecastCurrencyCode = "CNY"
    var failReads = false
    var readFailure: Throwable? = null
    var listing: (suspend (String) -> IncomePlanListResponseDto)? = null
    var history: (suspend (Long?) -> IncomeHistoryResponseDto)? = null
    var loseResponse = true
    val calls = mutableListOf<Pair<IncomePlanUpdateRequestDto, String>>()
    val results = mutableMapOf<String, IncomePlanDto>()
    val creationCalls = mutableListOf<Pair<IncomePlanCreateRequestDto, String>>()
    val creationReceipts = mutableMapOf<String, IncomePlanDto>()
    val historyCalls = mutableListOf<String>()
    val service = object : ApiService by incomeProxy<ApiService>({ error("Unexpected remote method: $it") }) {
        override suspend fun incomePlanHistory(publicId: String, limit: Int, beforeVersion: Long?): IncomeHistoryResponseDto {
            if (failReads) throw java.net.UnknownHostException("Synthetic unavailable history read")
            readFailure?.let { throw it }
            history?.let { return it(beforeVersion) }
            check(publicId == current.publicId && limit == 20 && beforeVersion == null)
            historyCalls += publicId
            return IncomeHistoryResponseDto("income-ledger", publicId, listOf(IncomeRevisionDto(2, "edit",
                "2026-08-28T10:00:00Z", "2026-08", "2026-08", IncomeDefinitionDto("八月工资预测", "salary",
                    "monthly", null, 8000, "CNY", 31, "active"))), null)
        }

        override suspend fun listIncomePlans(status: String): IncomePlanListResponseDto {
            if (failReads) throw java.net.UnknownHostException("Synthetic unavailable management read")
            readFailure?.let { throw it }
            listing?.let { return it(status) }
            return IncomePlanListResponseDto(if (status == current.status) listOf(current) else emptyList(),
                current.amountCents, month, current.amountCents, 1, current.amountCents, homeCurrencyCode = forecastCurrencyCode)
        }

        override suspend fun archiveIncomePlan(publicId: String, request: com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto): IncomePlanDto =
            changeStatus(publicId, request.expectedRowVersion, "archived")

        override suspend fun restoreIncomePlan(publicId: String, request: com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto): IncomePlanDto =
            changeStatus(publicId, request.expectedRowVersion, "active")

        override suspend fun createIncomePlan(request: IncomePlanCreateRequestDto, idempotencyKey: String): IncomePlanDto {
            creationCalls += request to idempotencyKey
            val receipt = creationReceipts.getOrPut(idempotencyKey) {
                IncomePlanDto("created-income", request.label, request.sourceType, request.frequency, request.incomeMonth,
                    request.amountCents, request.payDay, "active", "2026-09-30T00:00:00Z", "2026-09-30T00:00:00Z",
                    1, null, request.homeCurrencyCode)
            }
            if (loseResponse) throw IOException("Synthetic lost creation acknowledgement")
            return receipt
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

    private fun changeStatus(publicId: String, version: Long, status: String): IncomePlanDto {
        check(publicId == current.publicId && version == current.rowVersion)
        current = current.copy(status = status, rowVersion = current.rowVersion + 1,
            archivedAt = if (status == "archived") "2026-09-30T15:30:00Z" else null)
        if (loseResponse) throw IOException("Synthetic lost status acknowledgement")
        return current
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
