package com.ticketbox.ui.navigation

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DataQualitySummaryDto
import com.ticketbox.data.repository.ApiServiceProvider
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.CategoryPreferenceRepository
import com.ticketbox.data.repository.DebtRepository
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.RepaymentDraftRepository
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.data.repository.ServerSessionBinding
import com.ticketbox.data.repository.TagRepository
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.PendingSessionRefresh
import com.ticketbox.security.RequestAuthSnapshot
import com.ticketbox.security.SessionCredentialRotator
import com.ticketbox.security.StoredSessionToken
import java.io.IOException
import java.lang.reflect.InvocationHandler
import java.lang.reflect.Proxy
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.flowOf

/**
 * Connected-test harness for the data-quality navigation contract.
 *
 * Builds a REAL [MainScreenFactory] (so the production `DataQualityRoute`
 * ViewModel wiring runs unmodified) on top of: an in-memory Room database, a
 * Proxy-backed [ApiService] whose only implemented endpoint is
 * `dataQualitySummary`, and a seeded local session so `LedgerRequestGuard`
 * binds requests exactly as in production. Every unrelated repository is a
 * real instance over the same plumbing; interface-only collaborators the
 * route never calls are loud proxies (an unexpected call throws).
 */
internal class DataQualityConnectedHarness : AutoCloseable {
    val screenFactory: MainScreenFactory
    val apiProbe: DataQualityApiProbe
    private val database: AppDatabase

    init {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        val probe = DataQualityApiProbe()
        apiProbe = probe
        val sessionRecord = fakeSessionRecord()
        val apiService = interfaceProxy<ApiService> { name ->
            when (name) {
                "dataQualitySummary" -> {
                    probe.dataQualityCallCount += 1
                    probe.summary
                }
                "pendingExpenses" -> {
                    probe.pendingExpensesCallCount += 1
                    emptyList<Any>()
                }
                else -> Unhandled
            }
        }
        val apiClient = object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = apiService
        }
        val sessionStore = interfaceProxy<LocalSessionStore> { name ->
            when (name) {
                "currentSession" -> sessionRecord
                "observeSession" -> flowOf(sessionRecord)
                "hasPersistedSessionState" -> true
                "getSessionRefresh" -> interfaceProxy<com.ticketbox.security.SessionRefreshStore>()
                else -> Unhandled
            }
        }
        val settingsStore = interfaceProxy<TicketboxSettingsStore> { name ->
            when (name) {
                "monthlyBudgetCents" -> null
                "lastUploadAtForLedger" -> null
                else -> Unhandled
            }
        }
        val credentials = FakeSessionCredentials(sessionRecord)
        val apiProvider = ApiServiceProvider(apiClient, sessionStore, credentials)
        val binding = ServerSessionBinding(
            apiClient = apiClient,
            settingsStore = settingsStore,
            sessionStore = sessionStore,
            credentials = credentials,
            apiProvider = apiProvider,
        )
        val repositories = MainFeatureRepositories(
            repository = ExpenseRepository(database.expenseDao(), binding),
            ledgerRepository = LedgerRepository(
                settingsStore = settingsStore,
                expenseDao = database.expenseDao(),
                sessionStore = sessionStore,
                apiProvider = apiProvider,
            ),
            recurringRepository = RecurringRepository(apiProvider),
            budgetRepository = BudgetRepository(apiProvider),
            reportsRepository = interfaceProxy<ReportsActions>(),
            incomePlanRepository = interfaceProxy<IncomePlanActions>(),
            debtRepository = DebtRepository(apiProvider),
            repaymentDraftRepository = RepaymentDraftRepository(apiProvider),
            outboxRepository = OutboxRepository(
                dao = database.pendingMutationDao(),
                bindingProvider = { com.ticketbox.data.repository.OutboxBinding.DEFAULT },
            ),
            tagRepository = TagRepository(apiProvider),
            categoryPreferenceRepository = CategoryPreferenceRepository(apiProvider),
        )
        screenFactory = MainScreenFactory(
            repositories = repositories,
            viewModelFactories = MainScreenViewModelFactories(
                settingsViewModelFactory = unusedViewModelFactory(),
                categoryRulesViewModelFactory = unusedViewModelFactory(),
                merchantAliasViewModelFactory = unusedViewModelFactory(),
                appearanceViewModelFactory = unusedViewModelFactory(),
            ),
        )
    }

    override fun close() {
        database.close()
    }

    private fun unusedViewModelFactory() = object : androidx.lifecycle.ViewModelProvider.Factory {}

    private fun fakeSessionRecord() = LocalSessionRecord(
        sessionGeneration = "gen-1",
        bindingRevision = "rev-1",
        serverId = "3f6f1f2c-0000-4000-8000-000000000001",
        dataGeneration = "3f6f1f2c-0000-4000-8000-000000000002",
        serverUrl = "https://fake.local",
        credential = StoredSessionToken(token = "token-1"),
        identity = LocalSessionIdentity(
            accountPublicId = "3f6f1f2c-0000-4000-8000-000000000003",
            devicePublicId = "3f6f1f2c-0000-4000-8000-000000000004",
            accountName = "QA",
            ledgerId = "ledger-1",
            ledgerName = "QA Ledger",
            deviceName = "QA Device",
            role = "owner",
            boundAt = "2026-01-01T00:00:00Z",
        ),
    )
}

internal class DataQualityApiProbe {
    var dataQualityCallCount = 0
    var pendingExpensesCallCount = 0

    /** Two actionable remediation rows: 缺商家 (inbox) + 已确认无图 (transactions).
     * Mutable so tests can simulate off-page remediation changing the summary. */
    var summary = DataQualitySummaryDto(
        pendingTotal = 5,
        missingAmount = 0,
        missingMerchant = 2,
        missingCategory = 0,
        missingCategoryPending = 0,
        missingCategoryConfirmed = 0,
        suspectedDuplicates = 0,
        confirmedWithoutImage = 3,
        readyToConfirm = 0,
        readyToConfirmCategorized = 0,
        oldestPendingAgeDays = 1,
        generatedAt = "2026-07-22T00:00:00Z",
    )
}

private class FakeSessionCredentials(
    private val record: LocalSessionRecord,
) : SessionCredentialRotator {
    override fun getToken(): String = record.credential.token

    override fun currentLedgerId(): String = record.identity.ledgerId

    override fun sessionGeneration(): String = record.sessionGeneration

    override fun requestAuthSnapshot(): RequestAuthSnapshot = RequestAuthSnapshot(
        credential = record.credential,
        ledgerId = record.identity.ledgerId,
        sessionGeneration = record.sessionGeneration,
        bindingRevision = record.bindingRevision,
    )

    override suspend fun beginOrReuseSessionRefresh(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh? = null

    override suspend fun resumeSessionRefresh(
        expectedSessionGeneration: String,
        expectedToken: String,
    ): PendingSessionRefresh? = null

    override suspend fun completeSessionRefreshIfCurrent(
        expectedSessionGeneration: String,
        expectedToken: String,
        refreshAttemptId: String,
        replacement: StoredSessionToken,
    ): Boolean = false
}

private val Unhandled = Any()

private inline fun <reified T> interfaceProxy(
    crossinline answer: (String) -> Any? = { Unhandled },
): T {
    val handler = InvocationHandler { _, method, _ ->
        when (method.name) {
            "toString" -> "FakeProxy(${T::class.java.simpleName})"
            "hashCode" -> 0
            "equals" -> false
            else -> {
                val answered = answer(method.name)
                if (answered !== Unhandled) answered else defaultValueFor(method.returnType, method.name)
            }
        }
    }
    return Proxy.newProxyInstance(
        T::class.java.classLoader,
        arrayOf(T::class.java),
        handler,
    ) as T
}

private fun defaultValueFor(type: Class<*>, methodName: String): Any? = when {
    type == java.lang.Boolean.TYPE -> false
    type == java.lang.Integer.TYPE -> 0
    type == java.lang.Long.TYPE -> 0L
    Flow::class.java.isAssignableFrom(type) -> emptyFlow<Any?>()
    type == Unit::class.java -> Unit
    // A loud default beats a silent null: any unstubbed business call must
    // surface as a failure, not as phantom data.
    else -> throw IOException("unhandled fake call: $methodName")
}
