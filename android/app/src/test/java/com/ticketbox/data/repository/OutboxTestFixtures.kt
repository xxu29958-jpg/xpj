package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import kotlinx.coroutines.flow.Flow
import java.time.Clock

internal fun testBudgetRepository(provider: ApiServiceProvider,
    outbox: OutboxRepository = testOutboxRepository(FakePendingMutationDao(),
        bindingProvider = { provider.currentSession().toOutboxBinding() })): BudgetRepository {
    val adapters = com.ticketbox.OutboxAdapterGraph()
    return BudgetRepository(provider, outbox, adapters.budgetSaveAdapter, adapters.budgetReceiptAdapter,
        adapters.manualRateAdapter, adapters.manualRateReceiptAdapter)
}

internal fun testOutboxBinding(
    serverUrl: String = "https://api.example.com",
    ledgerId: String = "owner",
    owner: OutboxOwnerIdentity = requireNotNull(
        OutboxOwnerIdentity.fromOrNull(
            serverId = TEST_SERVER_ID,
            dataGeneration = TEST_DATA_GENERATION,
            accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
            devicePublicId = TEST_DEVICE_PUBLIC_ID,
        ),
    ),
): OutboxBinding = OutboxBinding(
    serverUrl = serverUrl,
    ledgerId = ledgerId,
    owner = owner,
)

internal fun testOutboxRepository(
    dao: PendingMutationDao,
    clock: Clock = Clock.systemUTC(),
    onEnqueued: () -> Unit = {},
    onClearAll: () -> Unit = {},
): OutboxRepository = OutboxRepository(
    onRowsDeleted = {},
    dao = dao,
    clock = clock,
    bindingProvider = ::testOutboxBinding,
    onEnqueued = onEnqueued,
    onClearAll = onClearAll,
)

internal fun testOutboxRepository(
    dao: PendingMutationDao,
    bindingProvider: () -> OutboxBinding,
    clock: Clock = Clock.systemUTC(),
    bindingChanges: Flow<OutboxBinding>? = null,
    onClearAll: () -> Unit = {},
): OutboxRepository = OutboxRepository(
    onRowsDeleted = {},
    dao = dao,
    clock = clock,
    bindingProvider = bindingProvider,
    bindingChanges = bindingChanges,
    onClearAll = onClearAll,
)

internal fun testExpenseOfflineMutationWiring(
    outbox: OutboxRepository = testOutboxRepository(FakePendingMutationDao()),
): ExpenseOfflineMutationWiring {
    val adapters = com.ticketbox.OutboxAdapterGraph()
    return ExpenseOfflineMutationWiring(outbox = outbox, correctionAdapter = adapters.correctionAdapter,
        billSplitReceiptAdapter = adapters.billSplitReceiptAdapter,
        billSplitCreateAdapter = adapters.billSplitCreateAdapter,
        legacyCorrectionAdapter = adapters.legacyCorrectionAdapter)
}

/** Real facade with a fake DAO whose binding follows the exact supplied session owner. */
internal fun expenseRepositoryFixture(
    expenseDao: com.ticketbox.data.local.ExpenseDao,
    binding: ServerSessionBinding,
    sessionCoordinator: LocalLedgerSessionCoordinator = LocalLedgerSessionCoordinator(binding.settingsStore, binding.sessionStore, expenseDao),
    deviceNameProvider: () -> String = ::defaultAndroidDeviceName,
): ExpenseRepository = ExpenseRepository(expenseDao, binding, sessionCoordinator, deviceNameProvider,
    testExpenseOfflineMutationWiring(OutboxRepository(onRowsDeleted = {}, dao = FakePendingMutationDao(),
        bindingProvider = { binding.sessionStore.currentSession().toOutboxBinding() })))
