package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.DashboardCardsUpdateRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewRequestDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerCreateRequestDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberRoleUpdateRequestDto
import com.ticketbox.data.remote.dto.LedgerSwitchResponseDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.OwnerTransferResponseDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.PairRequestDto
import com.ticketbox.data.remote.dto.PairResponseDto
import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.RefreshSessionResponseDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.data.remote.dto.StatusDto
import com.ticketbox.data.remote.dto.TagsDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.data.remote.dto.UserUiPreferencesDto
import com.ticketbox.data.remote.dto.UserUiPreferencesUpdateRequestDto
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.Response

internal class LedgerStubApiFactory(private val service: ApiService) : ApiServiceFactory {
    val tokenProviders: MutableList<() -> String?> = mutableListOf()

    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        tokenProviders += tokenProvider
        return service
    }
}

internal class StubApi(
    var listLedgersResult: LedgerListResponseDto? = null,
    var listLedgersError: Throwable? = null,
    var createResult: LedgerDto? = null,
    var switchResult: LedgerSwitchResponseDto? = null,
    var switchHandler: (suspend (String) -> LedgerSwitchResponseDto)? = null,
    var switchError: Throwable? = null,
    var membersResult: LedgerMemberListResponseDto? = null,
    var auditResult: LedgerAuditListResponseDto? = null,
    var roleUpdateResult: LedgerMemberDto? = null,
    var disableResult: LedgerMemberDto? = null,
    var transferResult: OwnerTransferResponseDto? = null,
    var previewResult: InvitationPreviewResponseDto? = null,
    var previewError: Throwable? = null,
    var acceptResult: InvitationAcceptResponseDto? = null,
    var acceptError: Throwable? = null,
    val switchRequests: MutableList<String> = mutableListOf(),
    val memberLedgerRequests: MutableList<String> = mutableListOf(),
    val auditRequests: MutableList<Pair<String, Int>> = mutableListOf(),
    val roleUpdateTargets: MutableList<Pair<String, Long>> = mutableListOf(),
    val roleUpdateRequests: MutableList<LedgerMemberRoleUpdateRequestDto> = mutableListOf(),
    val disableTargets: MutableList<Pair<String, Long>> = mutableListOf(),
    val transferTargets: MutableList<Pair<String, Long>> = mutableListOf(),
    val previewRequests: MutableList<InvitationPreviewRequestDto> = mutableListOf(),
    val acceptRequests: MutableList<InvitationAcceptRequestDto> = mutableListOf(),
) : ApiService {
    var onLedgerMembers: (() -> Unit)? = null
    var onListLedgers: (() -> Unit)? = null
    var onAcceptInvitation: (() -> Unit)? = null

    override suspend fun listLedgers(): LedgerListResponseDto {
        listLedgersError?.let { throw it }
        onListLedgers?.invoke()
        return listLedgersResult ?: LedgerListResponseDto(ledgers = emptyList())
    }

    override suspend fun createLedger(request: LedgerCreateRequestDto): LedgerDto {
        return createResult ?: LedgerDto(
            ledgerId = "L_new",
            name = request.name,
            role = "owner",
            isDefault = false,
            createdAt = "2026-01-01T00:00:00Z",
            archivedAt = null,
        )
    }

    override suspend fun switchLedger(ledgerId: String): LedgerSwitchResponseDto {
        switchRequests += ledgerId
        switchError?.let { throw it }
        switchHandler?.let { return it(ledgerId) }
        return switchResult ?: error("Unexpected switch call")
    }

    override suspend fun ledgerMembers(ledgerId: String): LedgerMemberListResponseDto {
        memberLedgerRequests += ledgerId
        onLedgerMembers?.invoke()
        return membersResult ?: error("Unexpected members call")
    }

    override suspend fun ledgerAudit(ledgerId: String, limit: Int): LedgerAuditListResponseDto {
        auditRequests += ledgerId to limit
        return auditResult ?: error("Unexpected audit call")
    }

    override suspend fun updateLedgerMemberRole(
        ledgerId: String,
        memberId: Long,
        request: LedgerMemberRoleUpdateRequestDto,
    ): LedgerMemberDto {
        roleUpdateTargets += ledgerId to memberId
        roleUpdateRequests += request
        return roleUpdateResult ?: error("Unexpected role update call")
    }

    override suspend fun disableLedgerMember(ledgerId: String, memberId: Long): LedgerMemberDto {
        disableTargets += ledgerId to memberId
        return disableResult ?: error("Unexpected disable call")
    }

    override suspend fun transferLedgerOwner(
        ledgerId: String,
        memberId: Long,
    ): OwnerTransferResponseDto {
        transferTargets += ledgerId to memberId
        return transferResult ?: error("Unexpected transfer call")
    }

    override suspend fun previewInvitation(
        request: InvitationPreviewRequestDto,
    ): InvitationPreviewResponseDto {
        previewRequests += request
        previewError?.let { throw it }
        return previewResult ?: error("Unexpected preview call")
    }

    override suspend fun acceptInvitation(request: InvitationAcceptRequestDto): InvitationAcceptResponseDto {
        acceptRequests += request
        acceptError?.let { throw it }
        onAcceptInvitation?.invoke()
        return acceptResult ?: error("Unexpected accept call")
    }

    override suspend fun pairDevice(request: PairRequestDto): PairResponseDto = ledgerUnsupported()
    override suspend fun refreshSession(): RefreshSessionResponseDto = ledgerUnsupported()
    override suspend fun checkAuth(): AuthCheckDto = ledgerUnsupported()
    override suspend fun pendingExpenses(): List<ExpenseDto> = ledgerUnsupported()
    override suspend fun confirmedExpenses(
        page: Int,
        pageSize: Int,
        month: String?,
        category: String?,
        tag: String?,
        timezone: String?,
    ): PaginatedExpensesDto = ledgerUnsupported()
    override suspend fun categories(): CategoriesDto = ledgerUnsupported()
    override suspend fun tags(): TagsDto = ledgerUnsupported()
    override suspend fun months(timezone: String?): MonthsDto = ledgerUnsupported()
    override suspend fun exportCsv(month: String?, category: String?, tag: String?, timezone: String?): Response<ResponseBody> = ledgerUnsupported()
    override suspend fun createManualExpense(request: ExpenseUpdateRequest): ExpenseDto = ledgerUnsupported()
    override suspend fun createNotificationDraft(
        request: com.ticketbox.data.remote.dto.NotificationDraftRequestDto,
    ): ExpenseDto = ledgerUnsupported()
    override suspend fun uploadScreenshot(file: MultipartBody.Part, timezone: String?): UploadResponseDto = ledgerUnsupported()
    override suspend fun expense(id: Long): ExpenseDto = ledgerUnsupported()
    override suspend fun updateExpense(id: Long, request: ExpenseUpdateRequest): ExpenseDto = ledgerUnsupported()
    override suspend fun expenseItems(id: Long): ExpenseItemsResponseDto = ledgerUnsupported()
    override suspend fun replaceExpenseItems(
        id: Long,
        request: ExpenseItemReplaceRequestDto,
    ): ExpenseItemsResponseDto = ledgerUnsupported()
    override suspend fun acknowledgeExpenseItemsMismatch(
        id: Long,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
    ): ExpenseItemsResponseDto = ledgerUnsupported()
    override suspend fun createBillSplitInvitation(
        id: Long,
        request: com.ticketbox.data.remote.dto.BillSplitInviteRequestDto,
    ): com.ticketbox.data.remote.dto.BillSplitSentDto = ledgerUnsupported()
    override suspend fun listBillSplitInbox(
        status: String?,
    ): com.ticketbox.data.remote.dto.BillSplitInboxListResponseDto = ledgerUnsupported()
    override suspend fun listBillSplitSent(): com.ticketbox.data.remote.dto.BillSplitSentListResponseDto = ledgerUnsupported()
    override suspend fun acceptBillSplitInvitation(
        publicId: String,
        request: com.ticketbox.data.remote.dto.BillSplitAcceptRequestDto,
    ): com.ticketbox.data.remote.dto.BillSplitInboxDto = ledgerUnsupported()
    override suspend fun rejectBillSplitInvitation(publicId: String): com.ticketbox.data.remote.dto.BillSplitInboxDto = ledgerUnsupported()
    override suspend fun cancelBillSplitInvitation(publicId: String): com.ticketbox.data.remote.dto.BillSplitSentDto = ledgerUnsupported()
    override suspend fun expenseSplits(id: Long): ExpenseSplitsResponseDto = ledgerUnsupported()
    override suspend fun replaceExpenseSplits(
        id: Long,
        request: ExpenseSplitReplaceRequestDto,
    ): ExpenseSplitsResponseDto = ledgerUnsupported()
    override suspend fun confirmExpense(
        id: Long,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
    ): ExpenseDto = ledgerUnsupported()
    override suspend fun rejectExpense(
        id: Long,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
    ): ExpenseDto = ledgerUnsupported()
    override suspend fun undoExpense(
        id: Long,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
    ): ExpenseDto = ledgerUnsupported()
    override suspend fun retryOcr(
        id: Long,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
    ): ExpenseDto = ledgerUnsupported()
    override suspend fun acceptPendingSuggestion(
        id: Long,
        decisionPublicId: String,
    ): StatusDto = ledgerUnsupported()
    override suspend fun rejectPendingSuggestion(
        id: Long,
        decisionPublicId: String,
    ): StatusDto = ledgerUnsupported()
    override suspend fun markNotDuplicate(
        id: Long,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
    ): ExpenseDto = ledgerUnsupported()
    override suspend fun expenseImage(id: Long): Response<ResponseBody> = ledgerUnsupported()
    override suspend fun expenseThumbnail(id: Long): Response<ResponseBody> = ledgerUnsupported()
    override suspend fun duplicates(): List<ExpenseDto> = ledgerUnsupported()
    override suspend fun categoryRules(): List<CategoryRuleDto> = ledgerUnsupported()
    override suspend fun createCategoryRule(request: CategoryRuleRequest): CategoryRuleDto = ledgerUnsupported()
    override suspend fun updateCategoryRule(
        id: Long,
        request: com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest,
    ): CategoryRuleDto = ledgerUnsupported()
    override suspend fun deleteCategoryRule(
        id: Long,
        request: com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest,
    ): StatusDto = ledgerUnsupported()
    override suspend fun merchantAliases(): MerchantAliasListDto = ledgerUnsupported()
    override suspend fun createMerchantAlias(request: MerchantAliasRequest): MerchantAliasDto = ledgerUnsupported()
    override suspend fun updateMerchantAlias(
        publicId: String,
        request: com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest,
    ): MerchantAliasDto = ledgerUnsupported()
    override suspend fun deleteMerchantAlias(
        publicId: String,
        request: com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest,
    ): StatusDto = ledgerUnsupported()
    override suspend fun undoMerchantAlias(publicId: String): MerchantAliasDto = ledgerUnsupported()
    override suspend fun undoCategoryRule(id: Long): com.ticketbox.data.remote.dto.CategoryRuleDto = ledgerUnsupported()
    override suspend fun ruleApplications(limit: Int): RuleApplicationListDto = ledgerUnsupported()
    override suspend fun rollbackRuleApplication(publicId: String): RuleApplicationRollbackDto = ledgerUnsupported()
    override suspend fun applyConfirmedRules(
        request: RuleApplyConfirmedRequestDto,
        limit: Int,
        maxScan: Int,
    ): RuleApplyConfirmedResponseDto = ledgerUnsupported()
    override suspend fun serverSettings(): ServerSettingsDto = ledgerUnsupported()
    override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?): MonthlyStatsDto = ledgerUnsupported()
    override suspend fun lifestyleStats(month: String?, timezone: String?): LifestyleStatsDto = ledgerUnsupported()
    override suspend fun reportsOverview(
        month: String?,
        granularity: String,
        topN: Int,
        merchantCategory: String?,
        rankingMetric: String,
        timezone: String?,
    ): ReportsOverviewDto = ledgerUnsupported()
    override suspend fun reportsOverviewCsv(
        month: String?,
        granularity: String,
        topN: Int,
        merchantCategory: String?,
        rankingMetric: String,
        timezone: String?,
    ): Response<ResponseBody> = ledgerUnsupported()
    override suspend fun goals(
        month: String?,
        includeArchived: Boolean,
        timezone: String?,
    ): GoalListResponseDto = ledgerUnsupported()
    override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?): GoalDto = ledgerUnsupported()
    override suspend fun goal(publicId: String, timezone: String?): GoalDto = ledgerUnsupported()
    override suspend fun updateGoal(
        publicId: String,
        request: GoalUpdateRequestDto,
        timezone: String?,
    ): GoalDto = ledgerUnsupported()
    override suspend fun archiveGoal(publicId: String, timezone: String?): GoalDto = ledgerUnsupported()
    override suspend fun dashboardCards(surface: String): DashboardCardsResponseDto = ledgerUnsupported()
    override suspend fun updateDashboardCards(
        request: DashboardCardsUpdateRequestDto,
        surface: String,
    ): DashboardCardsResponseDto = ledgerUnsupported()
    override suspend fun monthlyBudget(month: String, timezone: String?): BudgetMonthlyDto = ledgerUnsupported()
    override suspend fun updateMonthlyBudget(
        month: String,
        request: BudgetMonthlyUpdateRequestDto,
        timezone: String?,
    ): BudgetMonthlyDto = ledgerUnsupported()
    override suspend fun listIncomePlans(status: String): com.ticketbox.data.remote.dto.IncomePlanListResponseDto = ledgerUnsupported()
    override suspend fun createIncomePlan(request: com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto): com.ticketbox.data.remote.dto.IncomePlanDto = ledgerUnsupported()
    override suspend fun updateIncomePlan(publicId: String, request: com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto): com.ticketbox.data.remote.dto.IncomePlanDto = ledgerUnsupported()
    override suspend fun archiveIncomePlan(publicId: String, request: com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto): com.ticketbox.data.remote.dto.IncomePlanDto = ledgerUnsupported()
    override suspend fun restoreIncomePlan(publicId: String, request: com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto): com.ticketbox.data.remote.dto.IncomePlanDto = ledgerUnsupported()
    override suspend fun budgetDiscretionary(savingsTargetCents: Long, reservedBufferCents: Long): com.ticketbox.data.remote.dto.DiscretionaryResponseDto = ledgerUnsupported()
    override suspend fun budgetAdvise(request: com.ticketbox.data.remote.dto.BudgetAdviseRequestDto): com.ticketbox.data.remote.dto.BudgetAdviseResponseDto = ledgerUnsupported()
    override suspend fun recurringCandidates(timezone: String?): com.ticketbox.data.remote.dto.RecurringCandidatesResponseDto = ledgerUnsupported()
    override suspend fun recurringItems(
        status: String?,
        includeArchived: Boolean,
        month: String?,
        timezone: String?,
    ): RecurringItemListResponseDto = ledgerUnsupported()
    override suspend fun confirmRecurringCandidate(
        request: RecurringCandidateConfirmRequestDto,
        timezone: String?,
    ): RecurringItemDto = ledgerUnsupported()
    override suspend fun recurringItem(publicId: String, month: String?, timezone: String?): RecurringItemDto = ledgerUnsupported()
    override suspend fun pauseRecurringItem(publicId: String, request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest): RecurringItemDto = ledgerUnsupported()
    override suspend fun resumeRecurringItem(publicId: String, request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest): RecurringItemDto = ledgerUnsupported()
    override suspend fun archiveRecurringItem(publicId: String): RecurringItemDto = ledgerUnsupported()
    override suspend fun dataQualitySummary(): com.ticketbox.data.remote.dto.DataQualitySummaryDto = ledgerUnsupported()
    override suspend fun getUiPreferences(): Response<UserUiPreferencesDto> = ledgerUnsupported()
    override suspend fun putUiPreferences(
        request: UserUiPreferencesUpdateRequestDto,
    ): Response<UserUiPreferencesDto> = ledgerUnsupported()

    override suspend fun listBackgroundTasks(): com.ticketbox.data.remote.dto.BackgroundTaskListResponseDto =
        ledgerUnsupported()

    override suspend fun getBackgroundTask(
        publicId: String,
    ): com.ticketbox.data.remote.dto.BackgroundTaskDto = ledgerUnsupported()

    override suspend fun cancelBackgroundTask(
        publicId: String,
    ): com.ticketbox.data.remote.dto.BackgroundTaskDto = ledgerUnsupported()
}

internal class LedgerFakeSettingsStore : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = MutableStateFlow(BackgroundSettings())
    private var serverUrl: String? = null
    private var ledgerName: String? = null
    private var ledgersJson: String? = null
    private val ledgerIdFlow = MutableStateFlow<String?>(null)
    var capturedAccountName: String? = null
    var capturedDeviceName: String? = null
    var capturedRole: String? = null
    var capturedBoundAt: String? = null
    override fun serverUrl(): String? = serverUrl
    override fun appSkinKey(): String? = null
    override fun monthlyBudgetCents(): Long? = null
    override fun saveMonthlyBudgetCents(amountCents: Long?) = Unit
    override fun lastConfirmedSyncAt(): String? = null
    override fun accountName(): String? = capturedAccountName
    override fun ledgerName(): String? = ledgerName
    override fun activeLedgerId(): String? = ledgerIdFlow.value
    override fun activeLedgerName(): String? = ledgerName
    override fun availableLedgersJson(): String? = ledgersJson
    override fun observeActiveLedgerId(): Flow<String?> = ledgerIdFlow
    override fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
    }
    override fun saveAvailableLedgersJson(json: String?) { ledgersJson = json }
    override fun deviceName(): String? = capturedDeviceName
    override fun role(): String? = capturedRole
    override fun boundAt(): String? = capturedBoundAt
    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
        capturedAccountName = accountName
        capturedDeviceName = deviceName
        capturedRole = role
        capturedBoundAt = boundAt
    }
    override fun saveLastConfirmedSyncAt(value: String) = Unit
    override fun clearLastConfirmedSyncAt() = Unit
    override fun clearLastConfirmedSyncAtForLedger(ledgerId: String) = Unit
    override fun clearLedgerScopedRuntimeState() = Unit
    override fun lastUploadAt(): String? = null
    override fun saveLastUploadAt(value: String) = Unit
    override fun saveAppSkinKey(skinKey: String) = Unit
    override fun currencyCodeKey(): String? = null
    override fun saveCurrencyCodeKey(currencyKey: String) = Unit
    override fun observeCurrencyCodeKey(): Flow<String?> = MutableStateFlow(null)
    override fun saveServerUrl(serverUrl: String) {
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }
    override fun isBound(): Boolean = !serverUrl.isNullOrBlank()
    override fun markUnlocked() = Unit
    override fun markBackgrounded() = Unit
    override fun requiresUnlock(): Boolean = false
    override fun clear() {
        serverUrl = null; ledgerIdFlow.value = null; ledgerName = null; ledgersJson = null
    }
}

internal class LedgerFakeTokenStore : SessionTokenStore {
    private var token: String? = null
    override fun saveToken(token: String) { this.token = token }
    override fun getToken(): String? = token
    override fun clear() { token = null }
}

internal class LedgerFakeDao : ExpenseDao {
    private val map = linkedMapOf<Long, ExpenseEntity>()
    private val flows = mutableMapOf<String, MutableStateFlow<List<ExpenseEntity>>>()
    fun insertEntity(entity: ExpenseEntity) { map[entity.id] = entity }
    fun find(id: Long): ExpenseEntity? = map[id]
    override fun observeConfirmed(ledgerId: String): Flow<List<ExpenseEntity>> = flowFor(ledgerId)
    override suspend fun getConfirmed(ledgerId: String): List<ExpenseEntity> = map.values.filter { it.ledgerId == ledgerId }
    override suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity? =
        map.values.firstOrNull { it.ledgerId == ledgerId && it.serverId == serverId }
    override suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity> =
        map.values.filter { it.ledgerId == ledgerId && it.serverId in serverIds.toSet() }
    override suspend fun confirmedServerIdsForLedger(ledgerId: String): List<Long> =
        map.values.filter { it.ledgerId == ledgerId && it.status == "confirmed" }.map { it.serverId }
    override suspend fun insert(expense: ExpenseEntity): Long {
        map[expense.id] = expense
        return expense.id
    }
    override suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long> = expenses.map { insert(it) }
    override suspend fun update(expense: ExpenseEntity) { map[expense.id] = expense }
    override suspend fun updateAll(expenses: List<ExpenseEntity>) { expenses.forEach { update(it) } }
    override suspend fun clear() { map.clear() }
    override suspend fun clearForLedger(ledgerId: String) {
        val ids = map.values.filter { it.ledgerId == ledgerId }.map { it.id }
        ids.forEach { map.remove(it) }
    }
    override suspend fun deleteConfirmedForLedger(ledgerId: String) {
        val ids = map.values.filter { it.ledgerId == ledgerId && it.status == "confirmed" }.map { it.id }
        ids.forEach { map.remove(it) }
    }
    override suspend fun deleteConfirmedByServerIds(ledgerId: String, serverIds: List<Long>) {
        val remove = serverIds.toSet()
        val ids = map.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" && it.serverId in remove }
            .map { it.id }
        ids.forEach { map.remove(it) }
    }
    private fun flowFor(ledgerId: String): MutableStateFlow<List<ExpenseEntity>> =
        flows.getOrPut(ledgerId) { MutableStateFlow(emptyList()) }
}

internal fun ledgerUnsupported(): Nothing = error("Unexpected API call")

internal fun ledgerEntity(id: Long, ledgerId: String, serverId: Long): ExpenseEntity = ExpenseEntity(
    id = id,
    ledgerId = ledgerId,
    serverId = serverId,
    publicId = "p-$id",
    amountCents = 100,
    merchant = "m",
    category = "其他",
    note = null,
    source = "manual",
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = null,
    valueScore = null,
    regretScore = null,
    status = "confirmed",
    expenseTime = null,
    createdAt = "2026-01-01T00:00:00Z",
    confirmedAt = null,
    updatedAt = null,
    rowVersion = 1L,
)
