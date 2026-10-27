package com.ticketbox.data.repository

import android.content.Context
import android.content.ContextWrapper
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.RepositoryGraph
import com.ticketbox.RepositoryGraphDependencies
import com.ticketbox.RepositoryGraphOutbox
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.LocalSettingsStore
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
import com.ticketbox.data.remote.dto.DebtKindSetRequestDto
import com.ticketbox.data.remote.dto.DebtRepaymentReceiptDto
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import com.ticketbox.data.remote.dto.DebtActivityListDto
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
    private val settingsContext = object : ContextWrapper(context) {
        override fun getApplicationContext(): Context = this
        override fun getSharedPreferences(preferenceName: String, mode: Int) =
            context.getSharedPreferences("$name.$preferenceName", mode)
    }
    // Read-retirement markers must survive a reader's cancellation and the Room reopen.
    private val readSettings = LocalSettingsStore(settingsContext)
    private var database: AppDatabase? = null
    val clock: Clock = Clock.fixed(Instant.parse("2026-09-30T15:30:00Z"), ZoneOffset.UTC)
    val network = DebtAdjustmentConnectedNetwork()
    private val adapters = OutboxAdapterGraph()
    var session = debtAdjustmentConnectedSession()
    var scheduleCalls = 0
    private lateinit var apiProvider: ApiServiceProvider
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
        apiProvider = ApiServiceProvider(factory, sessions, credentials)
        return RepositoryGraph(RepositoryGraphDependencies(db, ApiClient(), readSettings,
            sessions, credentials, apiProvider, RepositoryGraphOutbox(outbox, adapters)))
            .also { graph = it }
    }

    fun stored(): List<Map<String, String?>> = requireNotNull(database).openHelper.readableDatabase
        .query("SELECT * FROM pending_mutations ORDER BY id").use { cursor -> buildList {
            while (cursor.moveToNext()) add(cursor.columnNames.mapIndexed { index, column -> column to cursor.getString(index) }.toMap())
        } }

    fun cachedDebtDetails(): List<Map<String, String?>> = requireNotNull(database).openHelper.readableDatabase
        .query("SELECT * FROM stats_projection_cache WHERE kind = 'debt_detail' ORDER BY bindingKey, tag, homeCurrencyCode")
        .use { cursor -> buildList {
            while (cursor.moveToNext()) add(cursor.columnNames.mapIndexed { index, column -> column to cursor.getString(index) }.toMap())
        } }

    fun setStoredMutationStatus(id: Long, status: String) {
        requireNotNull(database).openHelper.writableDatabase.execSQL(
            "UPDATE pending_mutations SET status = ? WHERE id = ?", arrayOf<Any>(status, id))
    }

    suspend fun drain(maxAttempts: Int = 10) = OutboxDrainEngine(outbox,
        listOf(RecordDebtAdjustmentDispatcher(LedgerRequestGuard(apiProvider), adapters.debt.debtAdjustmentAdapter),
            RecordDebtRepaymentDispatcher(LedgerRequestGuard(apiProvider), adapters.debt.debtRepaymentAdapter, adapters.debt.debtRepaymentReceiptAdapter),
            VoidDebtDispatcher(LedgerRequestGuard(apiProvider), adapters.debt.debtVoidAdapter, adapters.debt.debtVoidReceiptAdapter),
            VoidDebtRepaymentDispatcher(LedgerRequestGuard(apiProvider), adapters.debt.debtRepaymentVoidAdapter, adapters.debt.debtVoidReceiptAdapter),
            SetDebtKindDispatcher(LedgerRequestGuard(apiProvider), adapters.debt.debtKindAdapter, adapters.debt.debtVoidReceiptAdapter)),
        maxAttempts = maxAttempts, now = clock::millis).drainOnce()

    fun close() { database?.close(); context.deleteDatabase(name); readSettings.clear() }
}

internal class DebtAdjustmentConnectedNetwork {
    var current = DebtDto(
        publicId = "debt-original", ledgerId = "debt-adjustment-ledger", direction = "i_owe",
        counterpartyType = "external", counterpartyLabel = "原借款对象", principalAmountCents = 50_000,
        remainingAmountCents = 50_000, paidAmountCents = 0, status = "open", sourceType = "manual",
        homeCurrencyCode = "CNY", createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 2,
        repaymentCalendar = com.ticketbox.data.remote.dto.RepaymentCalendarDto(3, "Pacific/Honolulu"),
    )
    var failReads = false
    var readFailure: IOException = IOException("Synthetic unavailable debt read")
    var readGate: CompletableDeferred<Unit>? = null
    var loseResponse = true
    // Each scenario supplies its accepted read; this transport does not calculate server facts.
    var adjustmentResponse: DebtDto? = null
    var kindResponse: DebtDto? = null
    var repaymentResponse: DebtRepaymentReceiptDto? = null
    var activityResponse = DebtActivityListDto("debt-original", "CNY", emptyList(), 1, 20, 0)
    val calls = mutableListOf<Triple<String, DebtAdjustmentCreateRequestDto, String?>>()
    val kindCalls = mutableListOf<Triple<String, DebtKindSetRequestDto, String?>>()
    val repaymentCalls = mutableListOf<Triple<String, RepaymentCreateRequestDto, String?>>()
    val service = object : ApiService by debtAdjustmentProxy<ApiService>({ error("Unexpected remote method: $it") }) {
        override suspend fun setDebtKind(publicId: String, request: DebtKindSetRequestDto, idempotencyKey: String?): DebtDto {
            kindCalls += Triple(publicId, request, idempotencyKey)
            if (failReads) throw IOException("Synthetic offline classification write")
            val response = requireNotNull(kindResponse) { "Declare the accepted classification response" }
            if (loseResponse) throw IOException("Synthetic classification reply lost after acceptance")
            return response
        }

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

        override suspend fun debtActivity(publicId: String, page: Int, focusRepayment: String?): com.ticketbox.data.remote.dto.DebtActivityListDto {
            if (failReads) throw IOException("Synthetic unavailable repayment history")
            return activityResponse
        }

        override suspend fun recordDebtRepayment(publicId: String, request: RepaymentCreateRequestDto,
            idempotencyKey: String?): DebtRepaymentReceiptDto {
            repaymentCalls += Triple(publicId, request, idempotencyKey)
            val response = requireNotNull(repaymentResponse) { "Declare the accepted repayment receipt" }
            if (loseResponse) throw IOException("Synthetic lost response after repayment commit")
            return response
        }

        override suspend fun repaymentDrafts(status: String?) = RepaymentDraftListResponseDto(listOf(
            RepaymentDraftDto(publicId = "draft-original", source = "bank_app", amountCents = 1_000,
                homeCurrencyCode = "CNY", capturedAt = current.createdAt, status = "pending",
                suggestedDebtPublicId = current.publicId, createdAt = current.createdAt),
        ))

        override suspend fun recordDebtAdjustment(publicId: String, request: DebtAdjustmentCreateRequestDto,
            idempotencyKey: String?): DebtDto {
            calls += Triple(publicId, request, idempotencyKey)
            val response = requireNotNull(adjustmentResponse) { "Declare the accepted adjustment response" }
            if (loseResponse) throw IOException("Synthetic lost response after commit")
            return response
        }
    }

    private suspend fun readCanonicalDebt(): DebtDto {
        val snapshot = current
        val unavailable = failReads
        readGate?.await()
        if (unavailable) throw readFailure
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
    val list = DebtListViewModel(graph.debtRepository, graph.debtCreationRepository, graph.debtWriteRepository)
    val receivables = ReceivablesViewModel(graph.debtRepository, graph.debtWriteRepository)
    val goal = DebtGoalViewModel(graph.reportsRepository, graph.debtWriteRepository)
    val createGoal = CreateDebtGoalViewModel(graph.goalEditRepository, graph.debtRepository, graph.debtWriteRepository)
    val inbox = RepaymentDraftInboxViewModel(graph.repaymentDraftRepository, graph.debtRepository, graph.debtWriteRepository, graph.repaymentReviewRepository)

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
