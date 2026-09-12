package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseRevisionPage
import com.ticketbox.domain.model.ExpenseOffsetDraft
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.ExpenseOffsetMutationOutcome
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.ServerSettings
import kotlinx.coroutines.flow.Flow

/**
 * Compatibility facade for the existing Android repository entrypoint.
 *
 * ViewModels already depend on narrow action interfaces; this facade keeps the
 * constructor and concrete methods stable while implementation bodies live in
 * protocol-focused collaborators below.
 */
class ExpenseRepository(
    expenseDao: ExpenseDao,
    binding: ServerSessionBinding,
    sessionCoordinator: LocalLedgerSessionCoordinator = LocalLedgerSessionCoordinator(
        settingsStore = binding.settingsStore,
        sessionStore = binding.sessionStore,
        expenseDao = expenseDao,
    ),
    deviceNameProvider: () -> String = ::defaultAndroidDeviceName,
    offlineMutations: ExpenseOfflineMutationWiring,
) : ServerBindingRepository,
    PendingReviewActions,
    LedgerActions,
    GlobalSearchActions,
    StatsActions,
    ExpenseEditActions,
    ExpenseFactActions {
    private val core = ExpenseRepositoryCore(
        expenseDao = expenseDao,
        binding = binding,
        deviceNameProvider = deviceNameProvider,
        sessionCoordinator = sessionCoordinator,
        offlineMutations = offlineMutations,
    )
    internal val pendingEnrichmentTasks: PendingEnrichmentTaskReader =
        ExpensePendingEnrichmentRepository(core)
    /**
     * 见 [ExpenseRepositoryCore.onConfirmedCommitted]：确认态落本地缓存的单点回调
     * （轴 6 预算超支检测的触发接缝），AppContainer 构造后注入。
     */
    var onConfirmedCommitted: (ledgerId: String) -> Unit
        get() = core.onConfirmedCommitted
        set(value) {
            core.onConfirmedCommitted = value
        }

    /** See [ExpenseRepositoryCore.onFullConfirmedSyncSnapshot] — AppContainer
     *  wires it to the budget-advice freshness sink. */
    var onFullConfirmedSyncSnapshot: (stamp: String) -> Unit
        get() = core.onFullConfirmedSyncSnapshot
        set(value) {
            core.onFullConfirmedSyncSnapshot = value
        }

    private val bindingRepository = ExpenseBindingRepository(core)
    private val connectionRepository = ExpenseConnectionRepository(core)
    private val pendingRepository = ExpensePendingRepository(core)
    private val ledgerRepository = ExpenseLedgerRepositoryActions(core)
    private val statsRepository = ExpenseStatsRepositoryActions(core, ledgerRepository)
    private val searchRepository = ExpenseSearchRepositoryActions(core, pendingRepository, binding.settingsStore)
    private val detailRepository = ExpenseDetailRepository(core)
    private val correctionRepository = ExpenseCorrectionRepository(core, offlineMutations.outbox,
        offlineMutations.correctionAdapter, offlineMutations.legacyCorrectionAdapter)
    private val offsetRepository = ExpenseOffsetRepository(core, correctionRepository)
    private val billSplitRepository = ExpenseBillSplitRepository(core)
    private val backgroundTaskRepository = ExpenseBackgroundTaskRepository(core)

    override fun hasActiveSession(): Boolean = bindingRepository.hasActiveSession()

    override fun isBusinessSessionReady(): Boolean =
        bindingRepository.isBusinessSessionReady()

    override fun hasPendingBinding(): Boolean =
        bindingRepository.hasPendingBinding()

    fun currentLedgerRole(): String? = connectionRepository.currentLedgerRole()

    fun localBinding(): LocalBindingInfo? = core.localBinding()

    override fun canModifyLedger(): Boolean = pendingRepository.canModifyLedger()

    override fun currentTimezoneId(): String = core.currentTimezoneId()

    override fun observeActiveLedgerId(): Flow<String?> = pendingRepository.observeActiveLedgerId()

    override fun currentActiveLedgerId(): String? = pendingRepository.currentActiveLedgerId()


    override suspend fun bindServer(serverUrl: String, pairingCode: String): Result<BindServerResult> =
        bindingRepository.bindServer(serverUrl, pairingCode)

    override suspend fun resumePendingBinding(): Result<BindServerResult>? =
        bindingRepository.resumePendingBinding()

    override suspend fun abandonPendingBinding(): Boolean =
        bindingRepository.abandonPendingBinding()

    override suspend fun reconcileActiveSession(): Result<Unit>? =
        connectionRepository.reconcileActiveSession()

    suspend fun testConnection(): Result<Unit> = connectionRepository.testConnection()

    suspend fun runConnectionDiagnostics(binding: LogicalSessionBinding): Result<ConnectionDiagnostics> =
        connectionRepository.runConnectionDiagnostics(binding)

    override suspend fun fetchPending(): Result<List<Expense>> =
        pendingRepository.fetchPending()

    override suspend fun getCachedPending(): Result<List<Expense>> =
        pendingRepository.getCachedPending()

    override suspend fun syncPending(): Result<List<Expense>> =
        pendingRepository.syncPending()

    override suspend fun fetchExpenseFx(binding: LogicalSessionBinding, id: Long): Result<BackgroundTask?> =
        backgroundTaskRepository.fetchExpenseFx(binding, id)

    override suspend fun retryExpenseFx(binding: LogicalSessionBinding, expense: Expense): Result<BackgroundTask> =
        backgroundTaskRepository.retryExpenseFx(binding, expense)

    override suspend fun fetchExpenseForFxReview(binding: LogicalSessionBinding, id: Long): Result<Expense> =
        backgroundTaskRepository.fetchExpenseForFxReview(binding, id)

    override suspend fun fetchExpense(id: Long): Result<Expense> =
        detailRepository.fetchExpense(id)

    override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> =
        detailRepository.fetchExpenseFromLocalCache(id)

    override suspend fun fetchExpenseRevisions(
        id: Long,
        page: Int,
        pageSize: Int,
        snapshotRevision: Long?,
    ): Result<ExpenseRevisionPage> = correctionRepository.fetchRevisions(id, page, pageSize, snapshotRevision)

    override fun observeCorrections(): Flow<ExpenseCorrectionObservation> = correctionRepository.observe()

    internal suspend fun publishDeliveredCorrection(row: OutboxRow, expense: com.ticketbox.data.remote.dto.ExpenseDto) =
        correctionRepository.publishDelivered(row, expense)

    override suspend fun submitCorrection(expectedBinding: LogicalSessionBinding, expense: Expense,
        correction: ExpenseCorrectionDraft): Result<Long> = correctionRepository.submit(expectedBinding, expense, correction)

    override suspend fun recoverCorrection(expectedBinding: LogicalSessionBinding, rowId: Long, drop: Boolean): Result<Unit> =
        correctionRepository.recover(expectedBinding, rowId, drop)

    override suspend fun fetchExpenseFactBundle(id: Long): Result<ExpenseFactBundle> =
        offsetRepository.fetch(id)

    override suspend fun createExpenseOffsetAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        expense: Expense,
        draft: ExpenseOffsetDraft,
    ): Result<ExpenseOffsetMutationOutcome> = offsetRepository.createAllowingOffline(expectedBinding, expense, draft)

    internal fun canReplayExpenseOffset(row: OutboxRow): Boolean =
        row.lastError != "offset_create_requires_review" && core.offsetCreateAdapter?.readSupportedOffsetCreate(row) != null

    override suspend fun voidExpenseOffsetAllowingOffline(
        expense: Expense,
        offset: ExpenseOffsetFact,
        reason: String,
    ): Result<ExpenseOffsetMutationOutcome> = offsetRepository.voidAllowingOffline(expense, offset, reason)


    override suspend fun updateExpense(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense?,
    ): Result<Expense> = pendingRepository.updateExpense(id, draft, baseline)

    override suspend fun saveExpenseAllowingOffline(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense,
    ): Result<SaveOutcome> = pendingRepository.saveExpenseAllowingOffline(id, draft, baseline)

    override suspend fun fetchExpenseItems(id: Long): Result<ExpenseItems> =
        detailRepository.fetchExpenseItems(id)

    suspend fun replaceExpenseItems(
        id: Long,
        items: List<ExpenseItemDraft>,
        expectedRowVersion: Long,
    ): Result<ExpenseItems> =
        detailRepository.replaceExpenseItems(id, items, expectedRowVersion)

    suspend fun acknowledgeExpenseItemsMismatch(
        id: Long,
        expectedRowVersion: Long,
    ): Result<ExpenseItems> =
        detailRepository.acknowledgeExpenseItemsMismatch(id, expectedRowVersion)

    override suspend fun acknowledgeItemsMismatchAllowingOffline(
        expense: Expense,
        currentItems: ExpenseItems,
    ): Result<ItemsAckOutcome> =
        detailRepository.acknowledgeItemsMismatchAllowingOffline(expense, currentItems)

    override suspend fun replaceExpenseItemsAllowingOffline(
        expense: Expense,
        items: List<ExpenseItemDraft>,
        currentItems: ExpenseItems,
    ): Result<ReplaceItemsOutcome> =
        detailRepository.replaceExpenseItemsAllowingOffline(expense, items, currentItems)

    override suspend fun createBillSplitInvitation(
        expectedBinding: LogicalSessionBinding,
        expense: Expense,
        receiverAccountId: Long,
        receiverName: String,
        amountCents: Long,
    ): Result<Long> = billSplitRepository.createBillSplitInvitation(
        expectedBinding = expectedBinding,
        expense = expense,
        receiverAccountId = receiverAccountId,
        receiverName = receiverName,
        amountCents = amountCents,
    )

    override fun observeBillSplitCreations(): Flow<BillSplitCreationObservation> = billSplitRepository.observeCreations()
    fun describeBillSplitCreation(row: OutboxRow): PendingBillSplitCreation? = billSplitRepository.describeCreation(row)
    override suspend fun recoverBillSplitCreation(expectedBinding: LogicalSessionBinding, id: Long, drop: Boolean): Result<Unit> =
        billSplitRepository.recover(expectedBinding, id, drop)

    suspend fun fetchBillSplitInbox(binding: LogicalSessionBinding): Result<List<BillSplitInbox>> =
        billSplitRepository.fetchBillSplitInbox(binding)

    override suspend fun fetchBillSplitSent(binding: LogicalSessionBinding): Result<List<BillSplitSent>> =
        billSplitRepository.fetchBillSplitSent(binding)

    suspend fun acceptBillSplitInvitation(
        binding: LogicalSessionBinding,
        publicId: String,
        targetLedgerId: String,
    ): Result<BillSplitInbox> = billSplitRepository.acceptBillSplitInvitation(binding, publicId, targetLedgerId)

    suspend fun rejectBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitInbox> =
        billSplitRepository.rejectBillSplitInvitation(binding, publicId)

    override suspend fun cancelBillSplitInvitation(binding: LogicalSessionBinding, publicId: String): Result<BillSplitSent> =
        billSplitRepository.cancelBillSplitInvitation(binding, publicId)

    suspend fun fetchBackgroundTasks(binding: LogicalSessionBinding): Result<List<BackgroundTask>> =
        backgroundTaskRepository.fetchBackgroundTasks(binding)

    suspend fun cancelBackgroundTask(binding: LogicalSessionBinding, publicId: String): Result<BackgroundTask> =
        backgroundTaskRepository.cancelBackgroundTask(binding, publicId)

    override suspend fun fetchExpenseSplits(id: Long): Result<ExpenseSplits> =
        detailRepository.fetchExpenseSplits(id)

    suspend fun replaceExpenseSplits(
        id: Long,
        splits: List<ExpenseSplitDraft>,
        expectedRowVersion: Long,
    ): Result<ExpenseSplits> =
        detailRepository.replaceExpenseSplits(id, splits, expectedRowVersion)

    override suspend fun replaceExpenseSplitsAllowingOffline(
        expense: Expense,
        splits: List<ExpenseSplitDraft>,
        currentSplits: ExpenseSplits,
    ): Result<ReplaceSplitsOutcome> =
        detailRepository.replaceExpenseSplitsAllowingOffline(expense, splits, currentSplits)

    override suspend fun fetchSplitMembers(): Result<List<FamilyMember>> =
        detailRepository.fetchSplitMembers()

    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> =
        ledgerRepository.createManualExpense(draft)

    override suspend fun applyConfirmedBatch(
        expenses: List<Expense>,
        category: String?,
        tags: String?,
        reason: String,
    ): Result<BatchApplyResult> = ledgerRepository.applyConfirmedBatch(expenses, category, tags, reason)

    internal suspend fun createNotificationDraft(
        draft: NotificationDraft,
        expectedBinding: LogicalSessionBinding,
        notificationKey: String? = null,
    ): Result<Expense> = detailRepository.createNotificationDraft(draft, expectedBinding, notificationKey)

    override fun captureDeferredLedgerBinding(): LogicalSessionBinding? =
        core.ledgerRequestGuard.captureLogicalBinding()

    internal fun observeLedgerAccess(): Flow<LedgerAccessContext?> = core.apiProvider.observeActiveLedgerAccess()

    internal suspend fun describeManualCreation(row: OutboxRow): ManualExpenseCreationProjection? = core.describeManualCreation(row)

    internal suspend fun stopManualCreation(row: OutboxRow): Result<Unit> = core.stopManualCreation(row)

    override suspend fun createRepaymentDraftFromExpense(
        expectedBinding: LogicalSessionBinding,
        expense: Expense,
    ): Result<RepaymentDraft> = detailRepository.createRepaymentDraftFromExpense(expectedBinding, expense)

    override suspend fun confirmExpense(id: Long, expectedRowVersion: Long): Result<Expense> =
        pendingRepository.confirmExpense(id, expectedRowVersion)

    override suspend fun rejectExpense(id: Long, expectedRowVersion: Long): Result<Expense> =
        pendingRepository.rejectExpense(id, expectedRowVersion)

    override suspend fun confirmExpenseAllowingOffline(expense: Expense): Result<ExpenseStateOutcome> =
        pendingRepository.confirmExpenseAllowingOffline(expense)

    override suspend fun rejectExpenseAllowingOffline(expense: Expense): Result<ExpenseStateOutcome> =
        pendingRepository.rejectExpenseAllowingOffline(expense)

    override suspend fun undoRejectExpense(id: Long, expectedRowVersion: Long): Result<Expense> =
        pendingRepository.undoRejectExpense(id, expectedRowVersion)

    override suspend fun markNotDuplicateAllowingOffline(expense: Expense): Result<ExpenseStateOutcome> =
        pendingRepository.markNotDuplicateAllowingOffline(expense)

    suspend fun retryOcr(id: Long, expectedRowVersion: Long): Result<Expense> =
        detailRepository.retryOcr(id, expectedRowVersion)

    override suspend fun retryOcrAllowingOffline(expense: Expense): Result<ExpenseStateOutcome> =
        detailRepository.retryOcrAllowingOffline(expense)

    override suspend fun recognizeTextAllowingOffline(expense: Expense, rawText: String): Result<ExpenseStateOutcome> =
        detailRepository.recognizeTextAllowingOffline(expense, rawText)

    override suspend fun markNotDuplicate(id: Long, expectedRowVersion: Long): Result<Expense> =
        pendingRepository.markNotDuplicate(id, expectedRowVersion)

    suspend fun fetchDuplicates(): Result<List<Expense>> =
        detailRepository.fetchDuplicates()

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> =
        pendingRepository.fetchThumbnail(id)

    override suspend fun fetchImage(id: Long): Result<ProtectedImage> =
        detailRepository.fetchImage(id)

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = ledgerRepository.syncConfirmed(
        month = month,
        category = category,
        tag = tag,
    )

    override suspend fun categories(): Result<List<String>> =
        pendingRepository.categories()

    override suspend fun tags(): Result<List<String>> =
        ledgerRepository.tags()

    override suspend fun months(): Result<List<String>> =
        ledgerRepository.months()

    override suspend fun exportConfirmedCsv(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<CsvExport> = ledgerRepository.exportConfirmedCsv(
        month = month,
        category = category,
        tag = tag,
    )

    override fun observeConfirmed(): Flow<List<Expense>> =
        ledgerRepository.observeConfirmed()

    override fun observeConfirmedStream(): Flow<List<ConfirmedStreamItem>> =
        ledgerRepository.observeConfirmedStream()

    override fun recentSearches(): List<String> =
        searchRepository.recentSearches()

    override fun saveRecentSearches(queries: List<String>) =
        searchRepository.saveRecentSearches(queries)

    override fun observeStatsBinding(): Flow<LogicalSessionBinding?> = statsRepository.observeStatsBinding()

    override fun statsBinding(): LogicalSessionBinding? = statsRepository.statsBinding()

    override suspend fun monthlyStats(query: StatsQuery): Result<ReadSnapshot<MonthlyStats>> =
        statsRepository.monthlyStats(query)

    override suspend fun lifestyleStats(query: StatsQuery): Result<ReadSnapshot<LifestyleStats>> =
        statsRepository.lifestyleStats(query)

    override suspend fun dataQualitySummary(): Result<DataQualitySummary> =
        statsRepository.dataQualitySummary()

    suspend fun serverSettings(): Result<ServerSettings> =
        connectionRepository.serverSettings()

    override fun lastConfirmedSyncAt(): String? =
        connectionRepository.lastConfirmedSyncAt()

    override fun lastUploadAt(): String? =
        connectionRepository.lastUploadAt()

    suspend fun clearLocalCache() {
        connectionRepository.clearLocalCache()
    }

    override suspend fun clearBinding() {
        bindingRepository.clearBinding()
    }
}
