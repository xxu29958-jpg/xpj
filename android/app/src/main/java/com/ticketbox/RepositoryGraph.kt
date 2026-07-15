package com.ticketbox

import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.repository.ApiServiceProvider
import com.ticketbox.data.repository.CategoryRuleOfflineMutationWiring
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.DebtRepository
import com.ticketbox.data.repository.ExpenseOfflineMutationWiring
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.IncomePlanRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LocalLedgerSessionCoordinator
import com.ticketbox.data.repository.MerchantAliasOfflineMutationWiring
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.RepaymentDraftRepository
import com.ticketbox.data.repository.ReportsRepository
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.data.repository.ServerSessionBinding
import com.ticketbox.data.repository.TagRepository
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.SessionCredentialProvider

internal data class RepositoryGraphDependencies(
    val database: AppDatabase,
    val apiClient: ApiClient,
    val settingsStore: TicketboxSettingsStore,
    val sessionStore: LocalSessionStore,
    val credentials: SessionCredentialProvider,
    val apiServiceProvider: ApiServiceProvider,
    val outbox: RepositoryGraphOutbox,
)

internal data class RepositoryGraphOutbox(
    val repository: OutboxRepository,
    val adapters: OutboxAdapterGraph,
)

internal class RepositoryGraph(
    private val dependencies: RepositoryGraphDependencies,
) {
    private val database = dependencies.database
    private val apiClient = dependencies.apiClient
    private val settingsStore = dependencies.settingsStore
    private val sessionStore = dependencies.sessionStore
    private val credentials = dependencies.credentials
    private val apiServiceProvider = dependencies.apiServiceProvider
    private val outbox = dependencies.outbox.repository
    private val outboxAdapters = dependencies.outbox.adapters
    private val serverSessionBinding = ServerSessionBinding(
        apiClient = apiClient,
        settingsStore = settingsStore,
        sessionStore = sessionStore,
        credentials = credentials,
        apiProvider = apiServiceProvider,
    )

    private val ledgerSessionCoordinator = LocalLedgerSessionCoordinator(
        settingsStore = settingsStore,
        sessionStore = sessionStore,
        expenseDao = database.expenseDao(),
        outbox = outbox,
    )

    val expenseRepository = ExpenseRepository(
        expenseDao = database.expenseDao(),
        sessionCoordinator = ledgerSessionCoordinator,
        binding = serverSessionBinding,
        // PR-2g.3: pass the outbox + adapter so the PATCH expense
        // call site can fall back to enqueue on IOException.
        // PR-2g.7: + token adapter for confirm/reject offline routing.
        offlineMutations = ExpenseOfflineMutationWiring(
            outbox = outbox,
            patchExpenseAdapter = outboxAdapters.patchExpenseAdapter,
            expenseStateTokenAdapter = outboxAdapters.expenseStateTokenAdapter,
            replaceItemsAdapter = outboxAdapters.replaceItemsAdapter,
            replaceSplitsAdapter = outboxAdapters.replaceSplitsAdapter,
            recognizeTextAdapter = outboxAdapters.recognizeTextAdapter,
            // issue #65 slice 4: offline-aware manual create.
            manualCreateAdapter = outboxAdapters.manualCreateAdapter,
        ),
    )

    val ledgerRepository = LedgerRepository(
        settingsStore = settingsStore,
        expenseDao = database.expenseDao(),
        sessionStore = sessionStore,
        apiProvider = apiServiceProvider,
        sessionCoordinator = ledgerSessionCoordinator,
    )

    val recurringRepository = RecurringRepository(
        apiProvider = apiServiceProvider,
    )

    val budgetRepository = BudgetRepository(
        apiProvider = apiServiceProvider,
    )

    val incomePlanRepository = IncomePlanRepository(
        apiProvider = apiServiceProvider,
        // ADR-0042 Slice F: outbox + adapter for updateAllowingOffline.
        outbox = outbox,
        incomePlanUpdateAdapter = outboxAdapters.incomePlanUpdateAdapter,
    )

    // ADR-0049 §2 (slice 8): Debt entity repository. Direct-only online (no outbox surface).
    val debtRepository = DebtRepository(
        apiProvider = apiServiceProvider,
    )

    // ADR-0049 §杠杆③ (slice 3a): NLS 还款捕获复核箱仓库。direct-only online；NLS service 路由还款草稿到它。
    val repaymentDraftRepository = RepaymentDraftRepository(
        apiProvider = apiServiceProvider,
    )

    val reportsRepository = ReportsRepository(
        apiProvider = apiServiceProvider,
        // ADR-0042 Slice F: outbox + adapter for updateGoalAllowingOffline.
        outbox = outbox,
        goalUpdateAdapter = outboxAdapters.goalUpdateAdapter,
    )

    val ruleRepository = RuleRepository(
        binding = serverSessionBinding,
        onConfirmedChanged = { expenseRepository.syncConfirmed() },
        // PR-2g.4: outbox + adapter for updateCategoryRuleAllowingOffline.
        // PR-2g.5: + deleteAdapter for deleteCategoryRuleAllowingOffline.
        offlineMutations = CategoryRuleOfflineMutationWiring(
            outbox = outbox,
            updateAdapter = outboxAdapters.categoryRuleUpdateAdapter,
            deleteAdapter = outboxAdapters.categoryRuleDeleteAdapter,
        ),
    )

    val merchantRepository = MerchantRepository(
        binding = serverSessionBinding,
        // PR-2g.5: outbox + delete adapter.
        // PR-2g.6: + update adapter for updateMerchantAliasAllowingOffline.
        offlineMutations = MerchantAliasOfflineMutationWiring(
            outbox = outbox,
            deleteAdapter = outboxAdapters.merchantAliasDeleteAdapter,
            updateAdapter = outboxAdapters.merchantAliasUpdateAdapter,
        ),
    )

    // ADR-0043 slice C — tag management. Online-only (契约 7): no outbox / no
    // idempotency adapters, unlike MerchantRepository.
    val tagRepository = TagRepository(
        apiProvider = apiServiceProvider,
    )

    suspend fun replaceCredentialsForDebug(serverUrl: String, sessionToken: String) {
        ledgerSessionCoordinator.replaceCredentialsForDebug(serverUrl, sessionToken)
    }
}
