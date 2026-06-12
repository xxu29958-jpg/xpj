package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.security.SessionTokenStore
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
    apiClient: ApiServiceFactory,
    settingsStore: TicketboxSettingsStore,
    tokenStore: SessionTokenStore,
    deviceNameProvider: () -> String = ::defaultAndroidDeviceName,
    apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
    sessionCoordinator: LocalLedgerSessionCoordinator = LocalLedgerSessionCoordinator(
        settingsStore,
        tokenStore,
        expenseDao,
    ),
    /**
     * ADR-0038 PR-2g.3: optional outbox + adapter. When wired,
     * mutations whose direct ApiService call fails with IOException
     * fall back to enqueueing a PendingMutation row so the worker
     * (PR-2g.2) replays once connectivity returns. AppContainer
     * passes the real instances; existing tests that don't care
     * about offline routing default to ``null`` and keep the
     * pre-PR-2g.3 behaviour (IOException → safeCall failure).
     */
    outbox: OutboxRepository? = null,
    patchExpenseAdapter: JsonAdapter<ExpenseUpdateRequest>? = null,
    // ADR-0038 PR-2g.7: token-only adapter for the offline-aware
    // confirm / reject call sites. Same null-keeps-old-behaviour
    // contract as patchExpenseAdapter.
    expenseStateTokenAdapter: JsonAdapter<ExpenseStateTokenRequest>? = null,
    // PR-D: body-carrying adapter for the offline-aware items editor.
    replaceItemsAdapter: JsonAdapter<ExpenseItemReplaceRequestDto>? = null,
    // ADR-0042 Slice E-1: body-carrying adapter for the offline-aware splits editor.
    replaceSplitsAdapter: JsonAdapter<ExpenseSplitReplaceRequestDto>? = null,
    // ADR-0042 Slice E-2: body-carrying adapter for the offline-aware "粘贴文字识别".
    recognizeTextAdapter: JsonAdapter<ExpenseRecognizeTextRequestDto>? = null,
) : ServerBindingRepository, PendingReviewActions, LedgerActions, GlobalSearchActions, StatsActions, ExpenseEditActions {
    private val core = ExpenseRepositoryCore(
        expenseDao = expenseDao,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        deviceNameProvider = deviceNameProvider,
        apiProvider = apiProvider,
        sessionCoordinator = sessionCoordinator,
        outbox = outbox,
        patchExpenseAdapter = patchExpenseAdapter,
        expenseStateTokenAdapter = expenseStateTokenAdapter,
        replaceItemsAdapter = replaceItemsAdapter,
        replaceSplitsAdapter = replaceSplitsAdapter,
        recognizeTextAdapter = recognizeTextAdapter,
    )
    private val bindingRepository = ExpenseBindingRepository(core)
    private val connectionRepository = ExpenseConnectionRepository(core)
    private val pendingRepository = ExpensePendingRepository(core)
    private val ledgerRepository = ExpenseLedgerRepositoryActions(core)
    private val statsRepository = ExpenseStatsRepositoryActions(core, ledgerRepository)
    private val searchRepository = ExpenseSearchRepositoryActions(core, pendingRepository, settingsStore)
    private val detailRepository = ExpenseDetailRepository(core)
    private val billSplitRepository = ExpenseBillSplitRepository(core)
    private val backgroundTaskRepository = ExpenseBackgroundTaskRepository(core)

    fun currentLedgerRole(): String? = connectionRepository.currentLedgerRole()

    override fun canModifyLedger(): Boolean = pendingRepository.canModifyLedger()

    override fun observeActiveLedgerId(): Flow<String?> = pendingRepository.observeActiveLedgerId()

    override fun currentActiveLedgerId(): String? = pendingRepository.currentActiveLedgerId()

    override suspend fun bindServer(serverUrl: String, pairingCode: String): Result<BindServerResult> =
        bindingRepository.bindServer(serverUrl, pairingCode)

    suspend fun testConnection(): Result<Unit> = connectionRepository.testConnection()

    suspend fun runConnectionDiagnostics(): Result<ConnectionDiagnostics> =
        connectionRepository.runConnectionDiagnostics()

    override suspend fun fetchPending(): Result<List<Expense>> =
        pendingRepository.fetchPending()

    override suspend fun fetchExpense(id: Long): Result<Expense> =
        detailRepository.fetchExpense(id)

    override suspend fun uploadScreenshot(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
        preparationDurationMs: Long?,
        sourceSizeBytes: Long?,
        expectedLedgerId: String?,
    ): Result<Long> = pendingRepository.uploadScreenshot(
        fileName = fileName,
        contentType = contentType,
        bytes = bytes,
        preparationDurationMs = preparationDurationMs,
        sourceSizeBytes = sourceSizeBytes,
        expectedLedgerId = expectedLedgerId,
    )

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
        expenseId: Long,
        receiverAccountId: Long,
        amountCents: Long,
    ): Result<BillSplitSent> = billSplitRepository.createBillSplitInvitation(
        expenseId = expenseId,
        receiverAccountId = receiverAccountId,
        amountCents = amountCents,
    )

    suspend fun fetchBillSplitInbox(): Result<List<BillSplitInbox>> =
        billSplitRepository.fetchBillSplitInbox()

    override suspend fun fetchBillSplitSent(): Result<List<BillSplitSent>> =
        billSplitRepository.fetchBillSplitSent()

    suspend fun acceptBillSplitInvitation(
        publicId: String,
        targetLedgerId: String,
    ): Result<BillSplitInbox> = billSplitRepository.acceptBillSplitInvitation(publicId, targetLedgerId)

    suspend fun rejectBillSplitInvitation(publicId: String): Result<BillSplitInbox> =
        billSplitRepository.rejectBillSplitInvitation(publicId)

    override suspend fun cancelBillSplitInvitation(publicId: String): Result<BillSplitSent> =
        billSplitRepository.cancelBillSplitInvitation(publicId)

    suspend fun fetchBackgroundTasks(): Result<List<BackgroundTask>> =
        backgroundTaskRepository.fetchBackgroundTasks()

    suspend fun cancelBackgroundTask(publicId: String): Result<BackgroundTask> =
        backgroundTaskRepository.cancelBackgroundTask(publicId)

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
    ): Result<BatchApplyResult> = ledgerRepository.applyConfirmedBatch(expenses, category, tags)

    suspend fun createNotificationDraft(
        draft: NotificationDraft,
        expectedLedgerId: String? = null,
    ): Result<Expense> = detailRepository.createNotificationDraft(draft, expectedLedgerId)

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

    override fun recentSearches(): List<String> =
        searchRepository.recentSearches()

    override fun saveRecentSearches(queries: List<String>) =
        searchRepository.saveRecentSearches(queries)

    override suspend fun monthlyStats(month: String?, tag: String?): Result<MonthlyStats> =
        statsRepository.monthlyStats(month, tag)

    override suspend fun lifestyleStats(month: String?): Result<LifestyleStats> =
        statsRepository.lifestyleStats(month)

    suspend fun recurringCandidates(): Result<List<RecurringCandidate>> =
        detailRepository.recurringCandidates()

    override suspend fun dataQualitySummary(): Result<DataQualitySummary> =
        statsRepository.dataQualitySummary()

    suspend fun serverSettings(): Result<ServerSettings> =
        connectionRepository.serverSettings()

    override fun monthlyBudgetCents(): Long? =
        connectionRepository.monthlyBudgetCents()

    override fun lastConfirmedSyncAt(): String? =
        connectionRepository.lastConfirmedSyncAt()

    override fun lastUploadAt(): String? =
        connectionRepository.lastUploadAt()

    fun saveMonthlyBudgetCents(amountCents: Long?) {
        connectionRepository.saveMonthlyBudgetCents(amountCents)
    }

    suspend fun clearLocalCache() {
        connectionRepository.clearLocalCache()
    }

    override suspend fun clearBinding() {
        bindingRepository.clearBinding()
    }
}
