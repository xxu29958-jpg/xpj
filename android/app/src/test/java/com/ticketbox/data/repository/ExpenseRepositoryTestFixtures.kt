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
import com.ticketbox.data.remote.dto.ExpenseItemDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseSplitDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.NotificationDraftRequestDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.PairRequestDto
import com.ticketbox.data.remote.dto.PairResponseDto
import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import com.ticketbox.data.remote.dto.RuleApplicationBatchDto
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.data.remote.dto.RuleApplyPreviewItemDto
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
import java.io.IOException

internal class FakeApiServiceFactory(
    private val service: FakeApiService,
) : ApiServiceFactory {
    val tokenValues = mutableListOf<String?>()

    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        tokenValues += tokenProvider()
        return service
    }
}

internal class FakeApiService(
    private val events: MutableList<String>,
    private var confirmedFailuresRemaining: Int,
    private val checkAuthResult: AuthCheckDto? = null,
    private val serverSettingsResult: ServerSettingsDto? = null,
) : ApiService {
    var lastNotificationDraftRequest: NotificationDraftRequestDto? = null
    var lastConfirmedMonth: String? = null
    var lastConfirmedCategory: String? = null
    var lastConfirmedTag: String? = null
    val confirmedResponses = mutableMapOf<Int, PaginatedExpensesDto>()
    val applyConfirmedRequests = mutableListOf<RuleApplyConfirmedRequestDto>()
    val rollbackPublicIds = mutableListOf<String>()
    val merchantAliasRequests = mutableListOf<MerchantAliasRequest>()
    val merchantAliasPatchTargets = mutableListOf<String>()
    val merchantAliasDeleteTargets = mutableListOf<String>()
    val itemFetchIds = mutableListOf<Long>()
    val itemReplaceIds = mutableListOf<Long>()
    val itemReplaceRequests = mutableListOf<ExpenseItemReplaceRequestDto>()
    val splitFetchIds = mutableListOf<Long>()
    val splitReplaceIds = mutableListOf<Long>()
    val splitReplaceRequests = mutableListOf<ExpenseSplitReplaceRequestDto>()
    val expenseFetchIds = mutableListOf<Long>()
    val confirmExpenseIds = mutableListOf<Long>()
    val markNotDuplicateIds = mutableListOf<Long>()
    var onConfirmedRequest: (() -> Unit)? = null
    var onExpenseFetch: (() -> Unit)? = null
    var onConfirmExpense: (() -> Unit)? = null
    var onCheckAuth: (() -> Unit)? = null

    override suspend fun pairDevice(request: PairRequestDto): PairResponseDto {
        return PairResponseDto(
            sessionToken = "session-token",
            accountName = "我",
            ledgerId = "owner",
            ledgerName = "我的小票夹",
            deviceName = request.deviceName,
            role = "owner",
        )
    }

    override suspend fun confirmedExpenses(
        page: Int,
        pageSize: Int,
        month: String?,
        category: String?,
        tag: String?,
        timezone: String?,
    ): PaginatedExpensesDto {
        events += "syncConfirmed"
        lastConfirmedMonth = month
        lastConfirmedCategory = category
        lastConfirmedTag = tag
        onConfirmedRequest?.invoke()
        if (confirmedFailuresRemaining > 0) {
            confirmedFailuresRemaining -= 1
            throw IOException("restore unavailable")
        }
        confirmedResponses[page]?.let { return it }
        return PaginatedExpensesDto(
            items = listOf(confirmedExpenseDto()),
            page = page,
            pageSize = pageSize,
            total = 1,
        )
    }

    override suspend fun checkAuth(): AuthCheckDto {
        onCheckAuth?.invoke()
        return checkAuthResult ?: unsupported()
    }

    override suspend fun pendingExpenses(): List<ExpenseDto> = unsupported()

    override suspend fun categories(): CategoriesDto = unsupported()

    override suspend fun tags(): TagsDto = unsupported()

    override suspend fun months(timezone: String?): MonthsDto = unsupported()

    override suspend fun exportCsv(month: String?, category: String?, tag: String?, timezone: String?): Response<ResponseBody> = unsupported()

    override suspend fun createManualExpense(request: ExpenseUpdateRequest): ExpenseDto = unsupported()

    override suspend fun createNotificationDraft(request: NotificationDraftRequestDto): ExpenseDto {
        lastNotificationDraftRequest = request
        return ExpenseDto(
            id = 12,
            publicId = "8f939f48-e646-4afb-b54f-7bb6b536d9ef",
            amountCents = null,
            originalCurrency = request.originalCurrency,
            originalAmount = request.originalAmount,
            fxStatus = "pending",
            merchant = request.merchant,
            category = request.category ?: "其他",
            note = "",
            source = "通知草稿:微信",
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = "",
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "pending",
            expenseTime = request.expenseTime,
            createdAt = "2026-05-13T10:05:00Z",
            updatedAt = "2026-05-13T10:05:00Z",
            confirmedAt = null,
            rejectedAt = null,
        )
    }

    override suspend fun uploadScreenshot(file: MultipartBody.Part, timezone: String?): UploadResponseDto = unsupported()

    override suspend fun expense(id: Long): ExpenseDto {
        expenseFetchIds += id
        onExpenseFetch?.invoke()
        return confirmedExpenseDto()
    }

    override suspend fun updateExpense(id: Long, request: ExpenseUpdateRequest): ExpenseDto = unsupported()

    override suspend fun expenseItems(id: Long): ExpenseItemsResponseDto {
        itemFetchIds += id
        return expenseItemsResponse()
    }

    override suspend fun replaceExpenseItems(
        id: Long,
        request: ExpenseItemReplaceRequestDto,
    ): ExpenseItemsResponseDto {
        itemReplaceIds += id
        itemReplaceRequests += request
        return expenseItemsResponse()
    }

    override suspend fun acknowledgeExpenseItemsMismatch(id: Long): ExpenseItemsResponseDto {
        return expenseItemsResponse()
    }

    private fun stubBillSplitSent(): com.ticketbox.data.remote.dto.BillSplitSentDto =
        com.ticketbox.data.remote.dto.BillSplitSentDto(
            publicId = "test-public",
            status = "invited",
            amountCents = 2500,
            merchantSnapshot = null,
            categorySuggestion = null,
            expenseTimeSnapshot = null,
            expiresAt = "2026-06-23T00:00:00Z",
            createdAt = "2026-05-24T00:00:00Z",
            acceptedAt = null,
            rejectedAt = null,
            cancelledAt = null,
            expiredAt = null,
            receiverAccountId = 2,
            receiverDisplayNameSnapshot = null,
            senderExpenseId = 1,
        )
    private fun stubBillSplitInbox(): com.ticketbox.data.remote.dto.BillSplitInboxDto =
        com.ticketbox.data.remote.dto.BillSplitInboxDto(
            publicId = "test-public",
            status = "invited",
            amountCents = 2500,
            merchantSnapshot = null,
            categorySuggestion = null,
            expenseTimeSnapshot = null,
            expiresAt = "2026-06-23T00:00:00Z",
            createdAt = "2026-05-24T00:00:00Z",
            acceptedAt = null,
            rejectedAt = null,
            cancelledAt = null,
            expiredAt = null,
            senderAccountId = 1,
            senderDisplayName = "Sender",
        )
    override suspend fun createBillSplitInvitation(
        id: Long,
        request: com.ticketbox.data.remote.dto.BillSplitInviteRequestDto,
    ): com.ticketbox.data.remote.dto.BillSplitSentDto = stubBillSplitSent()
    override suspend fun listBillSplitInbox(): com.ticketbox.data.remote.dto.BillSplitInboxListResponseDto =
        com.ticketbox.data.remote.dto.BillSplitInboxListResponseDto(items = listOf(stubBillSplitInbox()))
    override suspend fun listBillSplitSent(): com.ticketbox.data.remote.dto.BillSplitSentListResponseDto =
        com.ticketbox.data.remote.dto.BillSplitSentListResponseDto(items = listOf(stubBillSplitSent()))
    override suspend fun acceptBillSplitInvitation(
        publicId: String,
        request: com.ticketbox.data.remote.dto.BillSplitAcceptRequestDto,
    ): com.ticketbox.data.remote.dto.BillSplitInboxDto = stubBillSplitInbox()
    override suspend fun rejectBillSplitInvitation(publicId: String): com.ticketbox.data.remote.dto.BillSplitInboxDto = stubBillSplitInbox()
    override suspend fun cancelBillSplitInvitation(publicId: String): com.ticketbox.data.remote.dto.BillSplitSentDto = stubBillSplitSent()

    override suspend fun expenseSplits(id: Long): ExpenseSplitsResponseDto {
        splitFetchIds += id
        return expenseSplitsResponse()
    }

    override suspend fun replaceExpenseSplits(
        id: Long,
        request: ExpenseSplitReplaceRequestDto,
    ): ExpenseSplitsResponseDto {
        splitReplaceIds += id
        splitReplaceRequests += request
        return expenseSplitsResponse()
    }

    override suspend fun confirmExpense(id: Long): ExpenseDto {
        confirmExpenseIds += id
        onConfirmExpense?.invoke()
        return confirmedExpenseDto()
    }

    override suspend fun rejectExpense(id: Long): ExpenseDto = unsupported()

    override suspend fun retryOcr(id: Long): ExpenseDto = unsupported()

    override suspend fun markNotDuplicate(id: Long): ExpenseDto {
        markNotDuplicateIds += id
        return confirmedExpenseDto()
    }

    override suspend fun expenseImage(id: Long): Response<ResponseBody> = unsupported()

    override suspend fun expenseThumbnail(id: Long): Response<ResponseBody> = unsupported()

    override suspend fun duplicates(): List<ExpenseDto> = unsupported()

    override suspend fun categoryRules(): List<CategoryRuleDto> = emptyList()

    override suspend fun createCategoryRule(request: CategoryRuleRequest): CategoryRuleDto = unsupported()

    override suspend fun updateCategoryRule(id: Long, request: CategoryRuleRequest): CategoryRuleDto = unsupported()

    override suspend fun deleteCategoryRule(id: Long): StatusDto = unsupported()

    override suspend fun merchantAliases(): MerchantAliasListDto = MerchantAliasListDto(
        items = listOf(
            merchantAliasDto(
                publicId = "alias-1",
                canonicalMerchant = "星巴克",
                canonicalKey = "星巴克",
                alias = "Starbucks",
                aliasKey = "starbucks",
                enabled = true,
            ),
        ),
    )

    override suspend fun createMerchantAlias(request: MerchantAliasRequest): MerchantAliasDto {
        merchantAliasRequests += request
        return merchantAliasDto(
            publicId = "alias-created",
            canonicalMerchant = requireNotNull(request.canonicalMerchant),
            canonicalKey = requireNotNull(request.canonicalMerchant),
            alias = requireNotNull(request.alias),
            aliasKey = requireNotNull(request.alias).lowercase(),
            enabled = request.enabled ?: true,
        )
    }

    override suspend fun updateMerchantAlias(
        publicId: String,
        request: MerchantAliasRequest,
    ): MerchantAliasDto {
        merchantAliasPatchTargets += publicId
        merchantAliasRequests += request
        return merchantAliasDto(
            publicId = publicId,
            canonicalMerchant = request.canonicalMerchant ?: "星巴克",
            canonicalKey = request.canonicalMerchant ?: "星巴克",
            alias = request.alias ?: "Starbucks",
            aliasKey = request.alias?.lowercase() ?: "starbucks",
            enabled = request.enabled ?: true,
        )
    }

    override suspend fun deleteMerchantAlias(publicId: String): StatusDto {
        merchantAliasDeleteTargets += publicId
        return StatusDto("ok")
    }

    override suspend fun ruleApplications(limit: Int): RuleApplicationListDto = RuleApplicationListDto(
        items = listOf(
            RuleApplicationBatchDto(
                publicId = "batch-1",
                status = "applied",
                pendingScanned = 9,
                changedCount = 1,
                createdAt = "2026-05-13T00:00:00Z",
                rolledBackAt = null,
            ),
        ),
    )

    override suspend fun rollbackRuleApplication(publicId: String): RuleApplicationRollbackDto {
        rollbackPublicIds += publicId
        return RuleApplicationRollbackDto(
            publicId = publicId,
            status = "rolled_back",
            changed = 1,
            skipped = 0,
            rolledBackAt = "2026-05-13T00:05:00Z",
        )
    }

    override suspend fun applyConfirmedRules(
        request: RuleApplyConfirmedRequestDto,
        limit: Int,
        maxScan: Int,
    ): RuleApplyConfirmedResponseDto {
        applyConfirmedRequests += request
        return RuleApplyConfirmedResponseDto(
            dryRun = !request.confirm,
            confirmedScanned = 9,
            changedCount = 1,
            items = if (request.confirm) {
                emptyList()
            } else {
                listOf(
                    RuleApplyPreviewItemDto(
                        id = 9,
                        merchant = "高德",
                        currentCategory = "其他",
                        suggestedCategory = "交通",
                        ruleKeyword = "高德",
                        reason = "merchant matched",
                    ),
                )
            },
            noMatchCount = 8,
            scanLimit = maxScan,
            previewToken = if (request.confirm) null else "preview-token",
        )
    }

    override suspend fun serverSettings(): ServerSettingsDto = serverSettingsResult ?: ServerSettingsDto(
        accountName = "我",
        ledgerId = "old",
        ledgerName = "旧账本",
        ledgerIsDefault = false,
        deviceName = "旧设备",
        role = "owner",
        status = "ok",
        storageStatus = "ok",
        pendingCount = 0,
        confirmedCount = 0,
        rejectedCount = 0,
        suspectedDuplicateCount = 0,
        uploadStorageBytes = 0,
        latestUploadAt = null,
    )

    override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?): MonthlyStatsDto = unsupported()

    override suspend fun lifestyleStats(month: String?, timezone: String?): LifestyleStatsDto = unsupported()
    override suspend fun reportsOverview(
        month: String?,
        granularity: String,
        topN: Int,
        merchantCategory: String?,
        rankingMetric: String,
        timezone: String?,
    ): ReportsOverviewDto = unsupported()
    override suspend fun reportsOverviewCsv(
        month: String?,
        granularity: String,
        topN: Int,
        merchantCategory: String?,
        rankingMetric: String,
        timezone: String?,
    ): Response<ResponseBody> = unsupported()
    override suspend fun goals(
        month: String?,
        includeArchived: Boolean,
        timezone: String?,
    ): GoalListResponseDto = unsupported()
    override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?): GoalDto = unsupported()
    override suspend fun goal(publicId: String, timezone: String?): GoalDto = unsupported()
    override suspend fun updateGoal(
        publicId: String,
        request: GoalUpdateRequestDto,
        timezone: String?,
    ): GoalDto = unsupported()
    override suspend fun archiveGoal(publicId: String, timezone: String?): GoalDto = unsupported()
    override suspend fun dashboardCards(surface: String): DashboardCardsResponseDto = unsupported()
    override suspend fun updateDashboardCards(
        request: DashboardCardsUpdateRequestDto,
        surface: String,
    ): DashboardCardsResponseDto = unsupported()
    override suspend fun monthlyBudget(month: String, timezone: String?): BudgetMonthlyDto = unsupported()
    override suspend fun updateMonthlyBudget(
        month: String,
        request: BudgetMonthlyUpdateRequestDto,
        timezone: String?,
    ): BudgetMonthlyDto = unsupported()
    override suspend fun listIncomePlans(status: String): com.ticketbox.data.remote.dto.IncomePlanListResponseDto = unsupported()
    override suspend fun createIncomePlan(request: com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto): com.ticketbox.data.remote.dto.IncomePlanDto = unsupported()
    override suspend fun updateIncomePlan(publicId: String, request: com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto): com.ticketbox.data.remote.dto.IncomePlanDto = unsupported()
    override suspend fun archiveIncomePlan(publicId: String): com.ticketbox.data.remote.dto.IncomePlanDto = unsupported()
    override suspend fun restoreIncomePlan(publicId: String): com.ticketbox.data.remote.dto.IncomePlanDto = unsupported()
    override suspend fun budgetDiscretionary(savingsTargetCents: Long, reservedBufferCents: Long): com.ticketbox.data.remote.dto.DiscretionaryResponseDto = unsupported()
    override suspend fun budgetAdvise(request: com.ticketbox.data.remote.dto.BudgetAdviseRequestDto): com.ticketbox.data.remote.dto.BudgetAdviseResponseDto = unsupported()
    override suspend fun recurringCandidates(timezone: String?): com.ticketbox.data.remote.dto.RecurringCandidatesResponseDto = unsupported()
    override suspend fun recurringItems(
        status: String?,
        includeArchived: Boolean,
        month: String?,
        timezone: String?,
    ): RecurringItemListResponseDto = unsupported()
    override suspend fun confirmRecurringCandidate(
        request: RecurringCandidateConfirmRequestDto,
        timezone: String?,
    ): RecurringItemDto = unsupported()
    override suspend fun recurringItem(publicId: String, month: String?, timezone: String?): RecurringItemDto = unsupported()
    override suspend fun pauseRecurringItem(publicId: String): RecurringItemDto = unsupported()
    override suspend fun resumeRecurringItem(publicId: String): RecurringItemDto = unsupported()
    override suspend fun archiveRecurringItem(publicId: String): RecurringItemDto = unsupported()
    override suspend fun dataQualitySummary(): com.ticketbox.data.remote.dto.DataQualitySummaryDto = unsupported()

    override suspend fun getUiPreferences(): Response<UserUiPreferencesDto> = unsupported()

    override suspend fun putUiPreferences(
        request: UserUiPreferencesUpdateRequestDto,
    ): Response<UserUiPreferencesDto> = unsupported()

    override suspend fun listBackgroundTasks(): com.ticketbox.data.remote.dto.BackgroundTaskListResponseDto =
        unsupported()

    override suspend fun getBackgroundTask(
        publicId: String,
    ): com.ticketbox.data.remote.dto.BackgroundTaskDto = unsupported()

    override suspend fun cancelBackgroundTask(
        publicId: String,
    ): com.ticketbox.data.remote.dto.BackgroundTaskDto = unsupported()

    override suspend fun listLedgers(): com.ticketbox.data.remote.dto.LedgerListResponseDto = unsupported()

    override suspend fun createLedger(request: com.ticketbox.data.remote.dto.LedgerCreateRequestDto): com.ticketbox.data.remote.dto.LedgerDto = unsupported()

    override suspend fun switchLedger(ledgerId: String): com.ticketbox.data.remote.dto.LedgerSwitchResponseDto = unsupported()

    override suspend fun ledgerMembers(
        ledgerId: String,
    ): com.ticketbox.data.remote.dto.LedgerMemberListResponseDto = unsupported()

    override suspend fun ledgerAudit(
        ledgerId: String,
        limit: Int,
    ): com.ticketbox.data.remote.dto.LedgerAuditListResponseDto = unsupported()

    override suspend fun updateLedgerMemberRole(
        ledgerId: String,
        memberId: Long,
        request: com.ticketbox.data.remote.dto.LedgerMemberRoleUpdateRequestDto,
    ): com.ticketbox.data.remote.dto.LedgerMemberDto = unsupported()

    override suspend fun disableLedgerMember(
        ledgerId: String,
        memberId: Long,
    ): com.ticketbox.data.remote.dto.LedgerMemberDto = unsupported()

    override suspend fun transferLedgerOwner(
        ledgerId: String,
        memberId: Long,
    ): com.ticketbox.data.remote.dto.OwnerTransferResponseDto = unsupported()

    override suspend fun previewInvitation(
        request: com.ticketbox.data.remote.dto.InvitationPreviewRequestDto,
    ): com.ticketbox.data.remote.dto.InvitationPreviewResponseDto = unsupported()

    override suspend fun acceptInvitation(
        request: com.ticketbox.data.remote.dto.InvitationAcceptRequestDto,
    ): com.ticketbox.data.remote.dto.InvitationAcceptResponseDto = unsupported()

    private fun merchantAliasDto(
        publicId: String,
        canonicalMerchant: String,
        canonicalKey: String,
        alias: String,
        aliasKey: String,
        enabled: Boolean,
    ): MerchantAliasDto = MerchantAliasDto(
        publicId = publicId,
        canonicalMerchant = canonicalMerchant,
        canonicalKey = canonicalKey,
        alias = alias,
        aliasKey = aliasKey,
        enabled = enabled,
        createdAt = "2026-05-13T00:00:00Z",
        updatedAt = "2026-05-13T00:05:00Z",
    )

    private fun expenseItemsResponse(): ExpenseItemsResponseDto = ExpenseItemsResponseDto(
        expenseId = 9,
        parentAmountCents = 1500,
        itemsTotalAmountCents = 500,
        mismatchCents = 1000,
        items = listOf(
            ExpenseItemDto(
                publicId = "item-1",
                position = 0,
                name = "拿铁",
                quantityText = "1杯",
                unitPriceCents = 500,
                amountCents = 500,
                category = "吃饭",
                rawText = null,
                confidence = null,
                isOcrDraft = false,
                createdAt = "2026-05-13T00:00:00Z",
                updatedAt = "2026-05-13T00:05:00Z",
            ),
        ),
    )

    private fun expenseSplitsResponse(): ExpenseSplitsResponseDto = ExpenseSplitsResponseDto(
        expenseId = 9,
        parentAmountCents = 1500,
        splitsTotalAmountCents = 6000,
        mismatchCents = -4500,
        splits = listOf(
            ExpenseSplitDto(
                publicId = "split-1",
                position = 0,
                memberId = 12,
                accountName = "家人",
                role = "member",
                amountCents = 6000,
                note = "一起吃饭",
                disabledAt = null,
                createdAt = "2026-05-13T00:00:00Z",
                updatedAt = "2026-05-13T00:05:00Z",
            ),
        ),
    )

    private fun confirmedExpenseDto(): ExpenseDto {
        return ExpenseDto(
            id = 9,
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            amountCents = 175479,
            merchant = "高德",
            category = "交通",
            note = "",
            source = "Android截图",
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = null,
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "confirmed",
            expenseTime = "2026-05-07T07:29:00Z",
            createdAt = "2026-05-09T08:08:13Z",
            updatedAt = "2026-05-09T08:12:40Z",
            confirmedAt = "2026-05-09T08:12:40Z",
            rejectedAt = null,
        )
    }
}

internal fun boundSettingsStore(): FakeTicketboxSettingsStore =
    FakeTicketboxSettingsStore().apply {
        saveServerUrl("https://api.example.com")
        saveIdentity(
            accountName = "我",
            ledgerId = "owner",
            ledgerName = "我的小票夹",
            deviceName = "Pixel",
            role = "owner",
            boundAt = "2026-05-01T00:00:00Z",
        )
    }

internal fun cachedConfirmedEntity(
    serverId: Long,
    publicId: String,
    merchant: String,
    ledgerId: String = "owner",
): ExpenseEntity =
    ExpenseEntity(
        ledgerId = ledgerId,
        serverId = serverId,
        publicId = publicId,
        amountCents = 1200,
        merchant = merchant,
        category = "交通",
        note = null,
        source = "缓存",
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
        expenseTime = "2026-05-01T00:00:00Z",
        createdAt = "2026-05-01T00:00:00Z",
        confirmedAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-01T00:00:00Z",
    )

internal class FakeTicketboxSettingsStore(
    private val events: MutableList<String> = mutableListOf(),
) : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = MutableStateFlow(BackgroundSettings())
    private var serverUrl: String? = null
    private var accountName: String? = null
    private val ledgerIdFlow = MutableStateFlow<String?>(null)
    private var ledgerName: String? = null
    private var availableLedgersJson: String? = null
    private var deviceName: String? = null
    private var role: String? = null
    private var boundAt: String? = null
    private val lastConfirmedSyncAtByLedger = mutableMapOf<String, String>()
    private var lastUploadAt: String? = null
    private var monthlyBudgetCents: Long? = null
    private var appSkinKey: String? = null
    var onSaveIdentity: (() -> Unit)? = null

    override fun serverUrl(): String? = serverUrl

    override fun appSkinKey(): String? = appSkinKey

    override fun monthlyBudgetCents(): Long? = monthlyBudgetCents

    override fun saveMonthlyBudgetCents(amountCents: Long?) {
        monthlyBudgetCents = amountCents
    }

    override fun lastConfirmedSyncAt(): String? =
        lastConfirmedSyncAtByLedger[activeLedgerId() ?: "legacy"]

    override fun accountName(): String? = accountName

    override fun ledgerName(): String? = ledgerName

    override fun activeLedgerId(): String? = ledgerIdFlow.value

    override fun activeLedgerName(): String? = ledgerName

    override fun availableLedgersJson(): String? = availableLedgersJson

    override fun observeActiveLedgerId(): Flow<String?> = ledgerIdFlow

    override fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        events += "saveActiveLedger"
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
    }

    override fun saveAvailableLedgersJson(json: String?) {
        availableLedgersJson = json
    }

    override fun deviceName(): String? = deviceName

    override fun role(): String? = role

    override fun boundAt(): String? = boundAt

    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        events += "saveIdentity"
        this.accountName = accountName
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
        this.deviceName = deviceName
        this.role = role
        this.boundAt = boundAt
        onSaveIdentity?.invoke()
    }

    override fun saveLastConfirmedSyncAt(value: String) {
        saveLastConfirmedSyncAtForLedger(activeLedgerId() ?: "legacy", value)
    }

    override fun saveLastConfirmedSyncAtForLedger(ledgerId: String, value: String) {
        lastConfirmedSyncAtByLedger[ledgerId] = value
    }

    override fun clearLastConfirmedSyncAt() {
        lastConfirmedSyncAtByLedger.remove(activeLedgerId() ?: "legacy")
    }

    override fun clearLastConfirmedSyncAtForLedger(ledgerId: String) {
        events += "clearLastConfirmedSyncAtForLedger:$ledgerId"
        lastConfirmedSyncAtByLedger.remove(ledgerId)
    }

    override fun clearLedgerScopedRuntimeState() {
        events += "clearLedgerScopedRuntimeState"
        lastConfirmedSyncAtByLedger.clear()
        lastUploadAt = null
    }

    override fun lastUploadAt(): String? = lastUploadAt

    override fun saveLastUploadAt(value: String) {
        lastUploadAt = value
    }

    override fun saveAppSkinKey(skinKey: String) {
        appSkinKey = skinKey
    }

    override fun currencyCodeKey(): String? = null

    override fun saveCurrencyCodeKey(currencyKey: String) = Unit

    override fun observeCurrencyCodeKey(): Flow<String?> = MutableStateFlow(null)

    override fun saveServerUrl(serverUrl: String) {
        events += "saveServerUrl"
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }

    override fun isBound(): Boolean = !serverUrl.isNullOrBlank()

    override fun markUnlocked() = Unit

    override fun markBackgrounded() = Unit

    override fun requiresUnlock(): Boolean = false

    override fun clear() {
        serverUrl = null
        accountName = null
        ledgerIdFlow.value = null
        ledgerName = null
        deviceName = null
        role = null
        boundAt = null
        lastConfirmedSyncAtByLedger.clear()
        lastUploadAt = null
    }
}

internal class FakeSessionTokenStore(
    private val events: MutableList<String> = mutableListOf(),
) : SessionTokenStore {
    private var token: String? = null

    override fun saveToken(token: String) {
        events += "saveToken"
        this.token = token
    }

    override fun getToken(): String? = token

    override fun clear() {
        token = null
    }
}

internal class FakeExpenseDao(
    private val events: MutableList<String> = mutableListOf(),
) : ExpenseDao {
    private val expenses = linkedMapOf<Long, ExpenseEntity>()
    private val flows = mutableMapOf<String, MutableStateFlow<List<ExpenseEntity>>>()
    private var nextId = 1L
    var onAfterApplyConfirmedSync: (() -> Unit)? = null

    override fun observeConfirmed(ledgerId: String): Flow<List<ExpenseEntity>> = flowFor(ledgerId)

    override suspend fun getConfirmed(ledgerId: String): List<ExpenseEntity> {
        return expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }
    }

    override suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity? {
        return expenses.values.firstOrNull { it.ledgerId == ledgerId && it.serverId == serverId }
    }

    override suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity> {
        val wanted = serverIds.toSet()
        return expenses.values.filter { it.ledgerId == ledgerId && it.serverId in wanted }
    }

    override suspend fun confirmedServerIdsForLedger(ledgerId: String): List<Long> {
        return expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .map { it.serverId }
    }

    override suspend fun insert(expense: ExpenseEntity): Long {
        val id = if (expense.id == 0L) nextId++ else expense.id
        expenses[id] = expense.copy(id = id)
        emit(expense.ledgerId)
        return id
    }

    override suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long> {
        return expenses.map { insert(it) }
    }

    override suspend fun update(expense: ExpenseEntity) {
        expenses[expense.id] = expense
        emit(expense.ledgerId)
    }

    override suspend fun updateAll(expenses: List<ExpenseEntity>) {
        expenses.forEach { update(it) }
    }

    override suspend fun clear() {
        events += "clear"
        val touched = expenses.values.map { it.ledgerId }.toSet()
        expenses.clear()
        touched.forEach { emit(it) }
    }

    override suspend fun clearForLedger(ledgerId: String) {
        events += "clearForLedger:$ledgerId"
        expenses.values
            .filter { it.ledgerId == ledgerId }
            .map { it.id }
            .forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    override suspend fun deleteConfirmedForLedger(ledgerId: String) {
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .map { it.id }
            .forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    override suspend fun deleteConfirmedByServerIds(ledgerId: String, serverIds: List<Long>) {
        val remove = serverIds.toSet()
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" && it.serverId in remove }
            .map { it.id }
            .forEach { expenses.remove(it) }
        emit(ledgerId)
    }

    override suspend fun applyConfirmedSyncForLedger(
        ledgerId: String,
        expenses: List<ExpenseEntity>,
        replaceCache: Boolean,
        pruneMissing: Boolean,
    ) {
        if (replaceCache) {
            clearForLedger(ledgerId)
        }
        expenses.forEach { upsertByServerIdForLedger(ledgerId, it) }
        if (pruneMissing) {
            val remoteServerIds = expenses.map { it.serverId }.toSet()
            val staleServerIds = confirmedServerIdsForLedger(ledgerId).filter { it !in remoteServerIds }
            if (staleServerIds.isNotEmpty()) {
                deleteConfirmedByServerIds(ledgerId, staleServerIds)
            }
        }
        onAfterApplyConfirmedSync?.invoke()
    }

    private fun flowFor(ledgerId: String): MutableStateFlow<List<ExpenseEntity>> =
        flows.getOrPut(ledgerId) { MutableStateFlow(snapshot(ledgerId)) }

    private fun snapshot(ledgerId: String): List<ExpenseEntity> =
        expenses.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" }
            .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }

    private fun emit(ledgerId: String) {
        flowFor(ledgerId).value = snapshot(ledgerId)
    }
}

private fun unsupported(): Nothing = error("Unexpected API call")
