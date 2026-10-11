package com.ticketbox.viewmodel

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.DebtCreationRepository
import com.ticketbox.data.repository.DebtWriteRepository
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakeApiServiceFactory
import com.ticketbox.data.repository.FakeExpenseDao
import com.ticketbox.data.repository.FakePendingMutationDao
import com.ticketbox.data.repository.TestSessionFixture
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.testIncomePlanRepository
import com.ticketbox.data.repository.IncomePlanRepository
import com.ticketbox.data.repository.testOutboxRepository
import com.ticketbox.data.repository.testApiServiceProvider
import com.ticketbox.data.repository.testServerSessionBinding
import com.ticketbox.data.repository.boundSettingsStore

internal fun outboxStatusHarness(onEnqueued: () -> Unit = {}, onRuleRefresh: suspend () -> Result<Unit> = { Result.success(Unit) }): OutboxStatusHarness {
    val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
    val api = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0))
    val binding = testServerSessionBinding(apiClient = api, settingsStore = boundSettingsStore(), tokenStore = tokenStore)
    val expenseRepository = com.ticketbox.data.repository.expenseRepositoryFixture(expenseDao = FakeExpenseDao(), binding = binding)
    val outbox = testOutboxRepository(dao = FakePendingMutationDao(), onEnqueued = onEnqueued)
    val recurringProvider = testApiServiceProvider(api, tokenStore)
    val recurringCache = FakeExpenseDao()
    return OutboxStatusHarness(
        outbox = outbox,
        expenseRepository = expenseRepository,
        debtCreation = DebtCreationRepository(
            testApiServiceProvider(api, tokenStore), outbox, OutboxAdapterGraph().debtCreateAdapter,
        ),
        incomePlans = testIncomePlanRepository(testApiServiceProvider(api, tokenStore), outbox,
            OutboxAdapterGraph().incomePlanSubmissionAdapter, OutboxAdapterGraph().incomePlanReceiptAdapter),
        debtWrites = DebtWriteRepository(testApiServiceProvider(api, tokenStore), outbox,
            OutboxAdapterGraph()),
        goalEdits = com.ticketbox.data.repository.GoalEditRepository(testApiServiceProvider(api, tokenStore), outbox,
            OutboxAdapterGraph().goalUpdateAdapter, OutboxAdapterGraph().goalReceiptAdapter, OutboxAdapterGraph().goalCreateAdapter, OutboxAdapterGraph().goalDebtLinksAdapter),
        budgetSaves = com.ticketbox.data.repository.testBudgetRepository(testApiServiceProvider(api, tokenStore), outbox),
        recurringItems = com.ticketbox.data.repository.RecurringRepository(recurringProvider, outbox,
            OutboxAdapterGraph(),
            queryReader = com.ticketbox.data.repository.RecurringQueryReader(recurringProvider, recurringCache,
                com.ticketbox.data.repository.testSnapshotCoordinator(recurringProvider, outbox, recurringCache))),
        rules = com.ticketbox.data.repository.RuleRepository(binding, onConfirmedChanged = onRuleRefresh, offlineMutations = OutboxAdapterGraph().let { adapters ->
            com.ticketbox.data.repository.CategoryRuleOfflineMutationWiring(outbox, adapters.categoryRuleUpdateAdapter,
                adapters.categoryRuleDeleteAdapter, adapters.categoryRuleSubmissionAdapter, adapters.categoryRuleReceiptAdapter,
                adapters.ruleApplicationAdapter, adapters.ruleApplicationReceiptAdapter)
        }),
    )
}

internal data class OutboxStatusHarness(
    val outbox: OutboxRepository,
    val expenseRepository: ExpenseRepository,
    val debtCreation: DebtCreationRepository,
    val incomePlans: IncomePlanRepository,
    val debtWrites: DebtWriteRepository,
    val goalEdits: com.ticketbox.data.repository.GoalEditRepository,
    val budgetSaves: com.ticketbox.data.repository.BudgetActions,
    val recurringItems: com.ticketbox.data.repository.RecurringManualMutationActions,
    val rules: com.ticketbox.data.repository.RuleRepository,
)
