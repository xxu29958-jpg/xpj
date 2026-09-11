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
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.DebtRepaymentEvaluationDto
import com.ticketbox.data.remote.dto.DebtGoalLinkViewDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentFactListDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import com.ticketbox.data.remote.dto.RepaymentDraftListResponseDto
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.viewmodel.CreateDebtGoalViewModel
import com.ticketbox.viewmodel.DebtGoalViewModel
import com.ticketbox.viewmodel.DebtListViewModel
import com.ticketbox.viewmodel.ReceivablesViewModel
import com.ticketbox.viewmodel.RepaymentDraftInboxViewModel
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
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.flowOf
import org.junit.Assert.assertEquals

/** Disk Room and production graph; session and remote IO are synthetic. No real account or financial data. */
internal class DebtAdjustmentConnectedFixture(private val context: Context, private val remote: ApiService? = null) {
    private val name = "debt-adjustment-continuity.db"
    private var database: AppDatabase? = null
    private val clock: Clock = Clock.fixed(Instant.parse("2026-09-30T15:30:00Z"), ZoneOffset.UTC)
    val network = DebtAdjustmentConnectedNetwork()
    private val adapters = OutboxAdapterGraph()
    private val session = debtAdjustmentConnectedSession()
    var scheduleCalls = 0
    lateinit var outbox: OutboxRepository
    lateinit var graph: RepositoryGraph
        private set


    fun reopen(): RepositoryGraph {
        database?.close()
        val db = Room.databaseBuilder(context, AppDatabase::class.java, name).build().also { database = it }
        outbox = OutboxRepository(db.pendingMutationDao(), clock, onRowsDeleted = {},
            bindingProvider = { session.toOutboxBinding() }, onEnqueued = { scheduleCalls += 1 })
        val sessions = debtAdjustmentProxy<LocalSessionStore> { method -> when (method) {
            "currentSession" -> session
            "observeSession" -> flowOf(session)
            "hasPersistedSessionState" -> true
            else -> error("Unexpected session method: $method")
        } }
        val credentials = SessionCredentialAdapter(sessions)
        val factory = object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = remote ?: network.service
        }
        return RepositoryGraph(RepositoryGraphDependencies(db, ApiClient(),
            debtAdjustmentProxy<TicketboxSettingsStore> { error("Unexpected settings: $it") },
            sessions, credentials, ApiServiceProvider(factory, sessions, credentials), RepositoryGraphOutbox(outbox, adapters)))
            .also { graph = it }
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
    var readGate: CompletableDeferred<Unit>? = null
    var loseResponse = true
    val calls = mutableListOf<Pair<DebtAdjustmentCreateRequestDto, String>>()
    val results = mutableMapOf<String, DebtDto>()
    val service = object : ApiService by debtAdjustmentProxy<ApiService>({ error("Unexpected remote method: $it") }) {
        override suspend fun debt(publicId: String): DebtDto {
            check(publicId == current.publicId)
            return readCanonicalDebt()
        }

        override suspend fun debts(lens: String?) = DebtListResponseDto(listOf(readCanonicalDebt()), "CNY")

        override suspend fun debtReceivables() = DebtListResponseDto(
            listOf(readCanonicalDebt()).filter { it.direction == "owed_to_me" }, "CNY",
        )

        override suspend fun goals(month: String?, includeArchived: Boolean,
            goalType: String?, timezone: String?): GoalListResponseDto {
            check(goalType == "debt_repayment")
            return GoalListResponseDto(listOf(adjustmentConnectedGoal(readCanonicalDebt())))
        }

        override suspend fun debtRepayments(publicId: String, page: Int) =
            RepaymentFactListDto(publicId, "CNY", emptyList(), page, 20, 0)

        override suspend fun repaymentDrafts(status: String?) = RepaymentDraftListResponseDto(listOf(
            RepaymentDraftDto(publicId = "draft-original", source = "bank_app", amountCents = 1_000,
                homeCurrencyCode = "CNY", capturedAt = current.createdAt, status = "pending",
                suggestedDebtPublicId = current.publicId, createdAt = current.createdAt),
        ))

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

    private suspend fun readCanonicalDebt(): DebtDto {
        val snapshot = current
        val unavailable = failReads
        readGate?.await()
        if (unavailable) throw IOException("Synthetic unavailable debt read")
        return snapshot
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

private fun adjustmentConnectedGoal(debt: DebtDto) = GoalDto(
    publicId = "goal-original", ledgerId = requireNotNull(debt.ledgerId), name = "原还债目标",
    goalType = "debt_repayment", period = "monthly", month = null, category = null,
    targetAmountCents = null, spentAmountCents = null, remainingAmountCents = null,
    progressPercent = null, progressState = "in_progress", status = "active",
    createdAt = debt.createdAt, updatedAt = debt.updatedAt, rowVersion = 1, archivedAt = null,
    debtRepayment = DebtRepaymentEvaluationDto(
        goalVersion = 1, evaluationState = "in_progress", needsReview = false,
        linkedDebts = listOf(DebtGoalLinkViewDto(
            debtPublicId = debt.publicId, status = debt.status, direction = debt.direction,
            counterpartyType = debt.counterpartyType, counterpartyLabel = debt.counterpartyLabel,
            principalAmountCents = debt.principalAmountCents,
            remainingAmountCents = debt.remainingAmountCents, homeCurrencyCode = debt.homeCurrencyCode,
        )), voidedDebtPublicIds = emptyList(),
    ),
)

internal fun assertRetainedAdjustmentSelection(model: ViewModel, publicId: String) {
    when (model) {
        is CreateDebtGoalViewModel -> {
            assertEquals("保留原目标名称", model.state.value.name)
            assertEquals(setOf(publicId), model.state.value.selectedDebtIds)
            assertEquals(3L, model.state.value.candidates.single().rowVersion)
        }
        is RepaymentDraftInboxViewModel -> {
            assertEquals(3L, model.state.value.targetDebts.single().rowVersion)
            assertEquals(3L, model.state.value.suggestedDebtByDraftId.getValue("draft-original").rowVersion)
        }
    }
}

/** The five retained production projections share one real Room/repository graph. */
internal class RetainedAdjustmentConsumers(graph: RepositoryGraph) {
    val list = DebtListViewModel(graph.debtRepository, graph.debtCreationRepository, graph.debtAdjustmentRepository)
    val receivables = ReceivablesViewModel(graph.debtRepository, graph.debtAdjustmentRepository)
    val goal = DebtGoalViewModel(graph.reportsRepository, graph.debtAdjustmentRepository)
    val createGoal = CreateDebtGoalViewModel(graph.reportsRepository, graph.debtRepository, graph.debtAdjustmentRepository)
    val inbox = RepaymentDraftInboxViewModel(graph.repaymentDraftRepository, graph.debtRepository, graph.debtAdjustmentRepository)

    fun balances(): List<Long?> = listOf(
        list.state.value.debts.singleOrNull()?.remainingAmountCents,
        receivables.state.value.receivables.singleOrNull()?.remainingAmountCents,
        goal.state.value.goals.singleOrNull()?.debtRepayment?.linkedDebts?.singleOrNull()?.remainingAmountCents,
        createGoal.state.value.candidates.singleOrNull()?.remainingAmountCents,
        inbox.state.value.targetDebts.singleOrNull()?.remainingAmountCents,
    )

    fun allReadsFailed() = listOf(list.state.value.error, receivables.state.value.error,
        goal.state.value.error, createGoal.state.value.loadError, inbox.state.value.error).all { it != null }

    fun refresh() {
        list.refresh()
        receivables.refresh()
        goal.refresh()
        createGoal.refreshCandidates()
        inbox.refresh()
    }

    fun close() {
        listOf<ViewModel>(list, receivables, goal, createGoal, inbox).forEach { it.viewModelScope.cancel() }
    }
}
