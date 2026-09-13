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
import com.ticketbox.data.repository.IncomePlanRepository
import com.ticketbox.data.repository.testOutboxRepository
import com.ticketbox.data.repository.testApiServiceProvider
import com.ticketbox.data.repository.testServerSessionBinding
import com.ticketbox.data.repository.boundSettingsStore

internal fun outboxStatusHarness(onEnqueued: () -> Unit = {}): OutboxStatusHarness {
    val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
    val api = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0))
    val binding = testServerSessionBinding(apiClient = api, settingsStore = boundSettingsStore(), tokenStore = tokenStore)
    val expenseRepository = com.ticketbox.data.repository.expenseRepositoryFixture(expenseDao = FakeExpenseDao(), binding = binding)
    val outbox = testOutboxRepository(dao = FakePendingMutationDao(), onEnqueued = onEnqueued)
    return OutboxStatusHarness(
        outbox = outbox,
        expenseRepository = expenseRepository,
        debtCreation = DebtCreationRepository(
            testApiServiceProvider(api, tokenStore), outbox, OutboxAdapterGraph().debtCreateAdapter,
        ),
        incomePlans = IncomePlanRepository(testApiServiceProvider(api, tokenStore), outbox,
            OutboxAdapterGraph().incomePlanSubmissionAdapter, OutboxAdapterGraph().incomePlanReceiptAdapter),
        debtWrites = DebtWriteRepository(testApiServiceProvider(api, tokenStore), outbox,
            OutboxAdapterGraph().debtAdjustmentAdapter, OutboxAdapterGraph().debtRepaymentAdapter),
        goalEdits = com.ticketbox.data.repository.GoalEditRepository(testApiServiceProvider(api, tokenStore), outbox,
            OutboxAdapterGraph().goalUpdateAdapter, OutboxAdapterGraph().goalReceiptAdapter, OutboxAdapterGraph().goalCreateAdapter),
        budgetSaves = com.ticketbox.data.repository.BudgetRepository(testApiServiceProvider(api, tokenStore), outbox,
            OutboxAdapterGraph().budgetSaveAdapter, OutboxAdapterGraph().budgetReceiptAdapter,
            OutboxAdapterGraph().manualRateAdapter, OutboxAdapterGraph().manualRateReceiptAdapter),
        recurringItems = com.ticketbox.data.repository.RecurringRepository(testApiServiceProvider(api, tokenStore), outbox,
            OutboxAdapterGraph().recurringCreateAdapter, OutboxAdapterGraph().recurringUpdateAdapter),
        rules = com.ticketbox.data.repository.RuleRepository(binding, offlineMutations = OutboxAdapterGraph().let { adapters ->
            com.ticketbox.data.repository.CategoryRuleOfflineMutationWiring(outbox, adapters.categoryRuleUpdateAdapter,
                adapters.categoryRuleDeleteAdapter, adapters.categoryRuleSubmissionAdapter, adapters.categoryRuleReceiptAdapter)
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
