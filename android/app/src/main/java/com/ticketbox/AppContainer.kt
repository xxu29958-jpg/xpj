package com.ticketbox

import android.content.Context
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.repository.ApiServiceProvider
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.IncomePlanRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LocalLedgerSessionCoordinator
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.OutboxMutationDispatcher
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.PatchExpenseDispatcher
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.ReportsRepository
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.security.SecureTokenStore

class AppContainer(context: Context) {
    private val appContext = context.applicationContext
    val settingsStore = LocalSettingsStore(appContext)
    val tokenStore = SecureTokenStore(appContext)
    private val database = AppDatabase.getDatabase(appContext)
    private val apiClient = ApiClient(appContext)
    private val apiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore)
    private val ledgerSessionCoordinator = LocalLedgerSessionCoordinator(
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        expenseDao = database.expenseDao(),
    )

    val expenseRepository = ExpenseRepository(
        expenseDao = database.expenseDao(),
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
        sessionCoordinator = ledgerSessionCoordinator,
    )

    val ledgerRepository = LedgerRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        expenseDao = database.expenseDao(),
        apiProvider = apiServiceProvider,
        sessionCoordinator = ledgerSessionCoordinator,
    )

    val recurringRepository = RecurringRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    val budgetRepository = BudgetRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    val incomePlanRepository = IncomePlanRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    val reportsRepository = ReportsRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    val ruleRepository = RuleRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
        onConfirmedChanged = { expenseRepository.syncConfirmed() },
    )

    val merchantRepository = MerchantRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    // ADR-0038 PR-2g.2: outbox drain plumbing.
    //
    // A dedicated Moshi instance for the outbox dispatcher layer.
    // We don't share the one ApiClient builds internally because it
    // lives in private scope; using a separate instance is fine
    // since Moshi adapters are immutable and stateless. The outbox
    // payloads we serialise here MUST line up with the Retrofit DTOs
    // (same nullability + @Json names) since the dispatcher
    // deserialises a row back into the same DTO shape on replay.
    private val outboxMoshi: Moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    val outboxRepository = OutboxRepository(dao = database.pendingMutationDao())

    /**
     * Registered dispatchers. PR-2g.2 wires only [PatchExpenseDispatcher]
     * — the reference dispatcher introduced in PR-2g. The remaining
     * 15 ``PendingMutationType``s land one-per-PR in 2g.3…2g.4; each
     * follow-up appends to this list. Until then,
     * [OutboxDrainEngine] marks rows of those types FAILED with
     * ``no_dispatcher_registered:<wire>`` (codex round-1 P2#5), which
     * is acceptable — no call site enqueues those types yet either.
     */
    private val outboxDispatchers: List<OutboxMutationDispatcher> = listOf(
        PatchExpenseDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = outboxMoshi.adapter(ExpenseUpdateRequest::class.java),
        ),
    )

    val outboxDrainEngine = OutboxDrainEngine(
        outbox = outboxRepository,
        dispatchers = outboxDispatchers,
    )
}
