package com.ticketbox

import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.repository.directWrite
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.repository.ApiServiceProvider
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.BudgetLocalStorage
import com.ticketbox.data.repository.CategoryPreferenceRepository
import com.ticketbox.data.repository.CategoryRuleOfflineMutationWiring
import com.ticketbox.data.repository.DebtRepository
import com.ticketbox.data.repository.DebtCreationRepository
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
    val portableExports = com.ticketbox.data.repository.PortableExportRepository(apiServiceProvider)
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
    private val debtQueries = com.ticketbox.data.repository.DebtQueryReader(apiServiceProvider, database.expenseDao(), ledgerSessionCoordinator)

    val expenseRepository = ExpenseRepository(
        expenseDao = database.expenseDao(),
        sessionCoordinator = ledgerSessionCoordinator,
        binding = serverSessionBinding,
        debtQueryReader = debtQueries,
        // PR-2g.3: pass the outbox + adapter so the PATCH expense
        // call site can fall back to enqueue on IOException.
        // PR-2g.7: + token adapter for confirm/reject offline routing.
        offlineMutations = ExpenseOfflineMutationWiring(
            outbox = outbox,
            patchExpenseAdapter = outboxAdapters.patchExpenseAdapter,
            correctionAdapter = outboxAdapters.correctionAdapter,
            legacyCorrectionAdapter = outboxAdapters.legacyCorrectionAdapter,
            billSplitCreateAdapter = outboxAdapters.billSplitCreateAdapter,
            billSplitReceiptAdapter = outboxAdapters.billSplitReceiptAdapter,
            expenseStateTokenAdapter = outboxAdapters.expenseStateTokenAdapter,
            replaceItemsAdapter = outboxAdapters.replaceItemsAdapter,
            replaceSplitsAdapter = outboxAdapters.replaceSplitsAdapter,
            recognizeTextAdapter = outboxAdapters.recognizeTextAdapter,
            // issue #65 slice 4: offline-aware manual create.
            manualCreateAdapter = outboxAdapters.manualCreateAdapter,
            recurringPaymentCreateAdapter = outboxAdapters.recurringPaymentCreateAdapter,
            offsetCreateAdapter = outboxAdapters.offsetCreateAdapter,
            offsetVoidAdapter = outboxAdapters.offsetVoidAdapter,
        ),
    )

    val ledgerRepository = LedgerRepository(
        settingsStore = settingsStore,
        expenseDao = database.expenseDao(),
        sessionStore = sessionStore,
        apiProvider = apiServiceProvider,
        sessionCoordinator = ledgerSessionCoordinator,
    )

    private val recurringQueries = com.ticketbox.data.repository.RecurringQueryReader(
        apiServiceProvider, database.expenseDao(), ledgerSessionCoordinator,
    )

    val recurringRepository = RecurringRepository(
        apiProvider = apiServiceProvider,
        outbox = outbox,
        createAdapter = outboxAdapters.recurringCreateAdapter,
        updateAdapter = outboxAdapters.recurringUpdateAdapter,
        occurrenceAdapter = outboxAdapters.recurringOccurrenceAdapter,
        queryReader = recurringQueries,
    )

    init {
        outbox.onRecurringDispatchPreparing = recurringQueries::prepareDispatch
        outbox.onRecurringDispatchFinished = recurringQueries::finishDispatch
        outbox.onRecurringAccepted = recurringQueries::invalidateAccepted
    }

    private val budgetQueries = com.ticketbox.data.repository.BudgetQueryReader(
        apiServiceProvider, database.expenseDao(), ledgerSessionCoordinator, outbox,
    )

    val budgetRepository = BudgetRepository(
        apiProvider = apiServiceProvider,
        outbox = outbox,
        adapters = outboxAdapters,
        localStorage = BudgetLocalStorage(database.monthlyArrangementCacheDao(), budgetQueries),
        sessionCoordinator = ledgerSessionCoordinator,
    )

    val incomePlanRepository = IncomePlanRepository(
        apiProvider = apiServiceProvider,
        // The editor persists its month-bearing original intent before dispatch.
        outbox = outbox,
        incomePlanSubmissionAdapter = outboxAdapters.incomePlanSubmissionAdapter,
        incomePlanReceiptAdapter = outboxAdapters.incomePlanReceiptAdapter,
        reads = com.ticketbox.data.repository.IncomePlanReadRepository(apiServiceProvider,
            database.incomeQueryCacheDao(), ledgerSessionCoordinator),
    )

    val debtRepository = DebtRepository(
        apiProvider = apiServiceProvider,
        queryReader = debtQueries,
        splitAgreement = com.ticketbox.data.repository.SplitAgreementRepository(
            apiServiceProvider, outbox, outboxAdapters.splitAgreementAdapter, debtQueries,
        ),
    )

    val debtWriteRepository = com.ticketbox.data.repository.DebtWriteRepository(
        apiServiceProvider, outbox, outboxAdapters,
    )

    val debtCreationRepository = DebtCreationRepository(
        apiProvider = apiServiceProvider,
        outbox = outbox,
        payloadAdapter = outboxAdapters.debtCreateAdapter,
    )

    // ADR-0049 §杠杆③ (slice 3a): NLS 还款捕获复核箱仓库。direct-only online；NLS service 路由还款草稿到它。
    val repaymentDraftRepository = RepaymentDraftRepository(
        apiProvider = apiServiceProvider,
        queryReader = debtQueries,
    )

    init {
        outbox.onDebtDispatchPreparing = debtRepository::prepareReadsBeforeDispatch
        outbox.onDebtDispatchFinished = debtRepository::finishReadDispatch
        outbox.onDebtAccepted = debtRepository::invalidateReadsAfterAccepted
    }

    init {
        outbox.onIncomeDispatchPreparing = incomePlanRepository.reads::prepareReadsBeforeDispatch
        outbox.onIncomeDispatchFinished = incomePlanRepository.reads::finishReadDispatch
        outbox.onIncomeAccepted = incomePlanRepository.reads::invalidateReadsAfterAccepted
    }

    val goalEditRepository = com.ticketbox.data.repository.GoalEditRepository(
        apiServiceProvider, outbox, outboxAdapters.goalUpdateAdapter, outboxAdapters.goalReceiptAdapter,
        outboxAdapters.goalCreateAdapter,
    )

    val reportsRepository = ReportsRepository(
        apiProvider = apiServiceProvider,
        expenseDao = database.expenseDao(),
        sessionCoordinator = ledgerSessionCoordinator,
    )

    init {
        ledgerRepository.restoreWithReadProtection = { binding, item, restore ->
            when (item.kind) {
                "monthly_budget" -> budgetQueries.directMutation(binding, item.resourceId) { restore() }
                "recurring_item" -> recurringQueries.directMutation(binding) { restore() }
                "income_plan" -> incomePlanRepository.reads.queries.directWrite(binding) { restore() }
                "goal" -> {
                    val result = restore()
                    withContext(NonCancellable) { reportsRepository.goalQueries.invalidate(binding) }
                    result
                }
                else -> restore()
            }
        }
    }

    val ruleRepository = RuleRepository(
        binding = serverSessionBinding,
        onConfirmedChanged = { expenseRepository.syncConfirmed() },
        offlineMutations = CategoryRuleOfflineMutationWiring(
            outbox = outbox,
            updateAdapter = outboxAdapters.categoryRuleUpdateAdapter,
            deleteAdapter = outboxAdapters.categoryRuleDeleteAdapter,
            submissionAdapter = outboxAdapters.categoryRuleSubmissionAdapter,
            receiptAdapter = outboxAdapters.categoryRuleReceiptAdapter,
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

    // 218-B2: 流水资料库自定义分类目录。Online-only OCC 删除（同 TagRepository 线）。
    val categoryPreferenceRepository = CategoryPreferenceRepository(
        apiProvider = apiServiceProvider,
    )

    suspend fun replaceCredentialsForDebug(serverUrl: String, sessionToken: String) {
        ledgerSessionCoordinator.replaceCredentialsForDebug(serverUrl, sessionToken)
    }
}
