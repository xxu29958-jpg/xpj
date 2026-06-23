package com.ticketbox.data.repository

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
import com.ticketbox.data.remote.dto.RefreshSessionResponseDto
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
    val merchantAliasUpdateRequests =
        mutableListOf<com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest>()
    val merchantAliasDeleteRequests =
        mutableListOf<com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest>()
    val merchantAliasPatchTargets = mutableListOf<String>()
    val merchantAliasDeleteTargets = mutableListOf<String>()
    val itemFetchIds = mutableListOf<Long>()
    val itemReplaceIds = mutableListOf<String>()
    val itemReplaceRequests = mutableListOf<ExpenseItemReplaceRequestDto>()
    val splitFetchIds = mutableListOf<Long>()
    val splitReplaceIds = mutableListOf<String>()
    val splitReplaceRequests = mutableListOf<ExpenseSplitReplaceRequestDto>()
    val expenseFetchIds = mutableListOf<Long>()
    val confirmExpenseIds = mutableListOf<String>()
    val markNotDuplicateIds = mutableListOf<String>()
    // suspend so a test can mutate the (suspend-API) FakeExpenseDao from the
    // hook — e.g. simulate a row being confirmed-and-cached mid-fetch.
    var onConfirmedRequest: (suspend () -> Unit)? = null
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

    override suspend fun refreshSession(): RefreshSessionResponseDto = unsupported()

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

    override suspend fun privateStatus(): com.ticketbox.data.remote.dto.StatusPrivateDto = unsupported()

    override suspend fun createInvitation(
        ledgerId: String,
        request: com.ticketbox.data.remote.dto.InvitationCreateRequestDto,
    ): com.ticketbox.data.remote.dto.InvitationCreateResponseDto = unsupported()

    override suspend fun pendingExpenses(): List<ExpenseDto> = unsupported()

    override suspend fun categories(): CategoriesDto = unsupported()

    override suspend fun tags(): TagsDto = unsupported()

    override suspend fun listManagedTags(): com.ticketbox.data.remote.dto.TagManagementListDto = unsupported()
    override suspend fun renameTag(publicId: String, request: com.ticketbox.data.remote.dto.TagRenameRequest): com.ticketbox.data.remote.dto.TagDetailDto = unsupported()
    override suspend fun deleteTag(publicId: String, request: com.ticketbox.data.remote.dto.TagDeleteRequest): com.ticketbox.data.remote.dto.TagMutationDto = unsupported()
    override suspend fun mergeTag(publicId: String, request: com.ticketbox.data.remote.dto.TagMergeRequest): com.ticketbox.data.remote.dto.TagMutationDto = unsupported()
    override suspend fun undoTagMutation(mutationPublicId: String, request: com.ticketbox.data.remote.dto.TagUndoRequest): com.ticketbox.data.remote.dto.TagUndoDto = unsupported()

    override suspend fun months(timezone: String?): MonthsDto = unsupported()

    override suspend fun exportCsv(month: String?, category: String?, tag: String?, timezone: String?): Response<ResponseBody> = unsupported()

    override suspend fun createManualExpense(request: com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto): ExpenseDto = unsupported()

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
            rowVersion = 1L,
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

    override suspend fun updateExpense(
        id: String,
        request: ExpenseUpdateRequest,
        idempotencyKey: String?,
    ): ExpenseDto = unsupported()

    override suspend fun expenseItems(id: Long): ExpenseItemsResponseDto {
        itemFetchIds += id
        return expenseItemsResponse()
    }

    override suspend fun replaceExpenseItems(
        id: String,
        request: ExpenseItemReplaceRequestDto,
        idempotencyKey: String?,
    ): ExpenseItemsResponseDto {
        itemReplaceIds += id
        itemReplaceRequests += request
        return expenseItemsResponse()
    }

    override suspend fun acknowledgeExpenseItemsMismatch(
        id: String,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        idempotencyKey: String?,
    ): ExpenseItemsResponseDto {
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
    override suspend fun listBillSplitInbox(
        status: String?,
    ): com.ticketbox.data.remote.dto.BillSplitInboxListResponseDto =
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
        id: String,
        request: ExpenseSplitReplaceRequestDto,
        idempotencyKey: String?,
    ): ExpenseSplitsResponseDto {
        splitReplaceIds += id
        splitReplaceRequests += request
        return expenseSplitsResponse()
    }

    override suspend fun confirmExpense(
        id: String,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        idempotencyKey: String?,
    ): ExpenseDto {
        confirmExpenseIds += id
        onConfirmExpense?.invoke()
        return confirmedExpenseDto()
    }

    override suspend fun rejectExpense(
        id: String,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        idempotencyKey: String?,
    ): ExpenseDto = unsupported()

    override suspend fun undoExpense(
        id: Long,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
    ): ExpenseDto = unsupported()

    override suspend fun retryOcr(
        id: String,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        idempotencyKey: String?,
    ): ExpenseDto = unsupported()

    override suspend fun recognizeText(
        id: String,
        request: com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto,
        idempotencyKey: String?,
    ): ExpenseDto = unsupported()

    override suspend fun acceptPendingSuggestion(
        id: Long,
        decisionPublicId: String,
    ): StatusDto = unsupported()

    override suspend fun rejectPendingSuggestion(
        id: Long,
        decisionPublicId: String,
    ): StatusDto = unsupported()

    override suspend fun markNotDuplicate(
        id: String,
        request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        idempotencyKey: String?,
    ): ExpenseDto {
        markNotDuplicateIds += id
        return confirmedExpenseDto()
    }

    override suspend fun expenseImage(id: Long): Response<ResponseBody> = unsupported()

    override suspend fun expenseThumbnail(id: Long): Response<ResponseBody> = unsupported()

    override suspend fun duplicates(): List<ExpenseDto> = unsupported()

    override suspend fun categoryRules(): List<CategoryRuleDto> = emptyList()

    override suspend fun createCategoryRule(request: CategoryRuleRequest): CategoryRuleDto = unsupported()

    override suspend fun updateCategoryRule(
        id: Long,
        request: com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest,
        idempotencyKey: String?,
    ): CategoryRuleDto = unsupported()

    override suspend fun deleteCategoryRule(
        id: Long,
        request: com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest,
        idempotencyKey: String?,
    ): StatusDto = unsupported()

    override suspend fun undoCategoryRule(id: Long): CategoryRuleDto = unsupported()

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
        request: com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest,
        idempotencyKey: String?,
    ): MerchantAliasDto {
        merchantAliasPatchTargets += publicId
        merchantAliasUpdateRequests += request
        return merchantAliasDto(
            publicId = publicId,
            canonicalMerchant = request.canonicalMerchant ?: "星巴克",
            canonicalKey = request.canonicalMerchant ?: "星巴克",
            alias = request.alias ?: "Starbucks",
            aliasKey = request.alias?.lowercase() ?: "starbucks",
            enabled = request.enabled ?: true,
        )
    }

    override suspend fun deleteMerchantAlias(
        publicId: String,
        request: com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest,
        idempotencyKey: String?,
    ): StatusDto {
        merchantAliasDeleteTargets += publicId
        merchantAliasDeleteRequests += request
        return StatusDto("ok")
    }

    val merchantAliasUndoTargets = mutableListOf<String>()

    override suspend fun undoMerchantAlias(publicId: String): MerchantAliasDto {
        merchantAliasUndoTargets += publicId
        return merchantAliasDto(
            publicId = publicId,
            canonicalMerchant = "星巴克",
            canonicalKey = "星巴克",
            alias = "Starbucks",
            aliasKey = "starbucks",
            enabled = true,
        )
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
        goalType: String?,
        timezone: String?,
    ): GoalListResponseDto = unsupported()
    override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?): GoalDto = unsupported()
    override suspend fun goal(publicId: String, timezone: String?): GoalDto = unsupported()
    override suspend fun updateGoal(
        publicId: String,
        request: GoalUpdateRequestDto,
        idempotencyKey: String?,
        timezone: String?,
    ): GoalDto = unsupported()
    override suspend fun archiveGoal(publicId: String, timezone: String?): GoalDto = unsupported()
    override suspend fun replaceGoalDebtLinks(
        publicId: String,
        request: com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto,
        idempotencyKey: String?,
        timezone: String?,
    ): GoalDto = unsupported()
    override suspend fun acknowledgeGoalIntegrityReview(
        publicId: String,
        request: com.ticketbox.data.remote.dto.DebtGoalIntegrityReviewRequestDto,
        idempotencyKey: String?,
        timezone: String?,
    ): GoalDto = unsupported()
    override suspend fun setGoalTargetDate(
        publicId: String,
        request: com.ticketbox.data.remote.dto.DebtGoalTargetDateRequestDto,
        idempotencyKey: String?,
        timezone: String?,
    ): GoalDto = unsupported()
    override suspend fun debts(): com.ticketbox.data.remote.dto.DebtListResponseDto = unsupported()
    override suspend fun debtReceivables(): com.ticketbox.data.remote.dto.DebtListResponseDto = unsupported()
    override suspend fun createDebt(
        request: com.ticketbox.data.remote.dto.DebtCreateRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.DebtDto = unsupported()
    override suspend fun debt(publicId: String): com.ticketbox.data.remote.dto.DebtDto = unsupported()
    override suspend fun recordDebtRepayment(
        publicId: String,
        request: com.ticketbox.data.remote.dto.RepaymentCreateRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.DebtDto = unsupported()
    override suspend fun recordDebtAdjustment(
        publicId: String,
        request: com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.DebtDto = unsupported()
    override suspend fun voidDebt(
        publicId: String,
        request: com.ticketbox.data.remote.dto.DebtVoidCreateRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.DebtDto = unsupported()
    override suspend fun setDebtKind(
        publicId: String,
        request: com.ticketbox.data.remote.dto.DebtKindSetRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.DebtDto = unsupported()
    override suspend fun forgiveDebt(
        publicId: String,
        request: com.ticketbox.data.remote.dto.DebtForgiveCreateRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.DebtDto = unsupported()
    override suspend fun repaymentProposals(
        publicId: String,
    ): com.ticketbox.data.remote.dto.MemberRepaymentProposalListResponseDto = unsupported()
    override suspend fun createRepaymentProposal(
        publicId: String,
        request: com.ticketbox.data.remote.dto.MemberRepaymentProposalCreateRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.MemberRepaymentProposalDto = unsupported()
    override suspend fun withdrawRepaymentProposal(
        publicId: String,
        proposalPublicId: String,
        request: com.ticketbox.data.remote.dto.MemberRepaymentProposalWithdrawRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.MemberRepaymentProposalDto = unsupported()
    override suspend fun confirmRepaymentProposal(
        publicId: String,
        proposalPublicId: String,
        request: com.ticketbox.data.remote.dto.MemberRepaymentProposalConfirmRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.DebtDto = unsupported()
    override suspend fun rejectRepaymentProposal(
        publicId: String,
        proposalPublicId: String,
        request: com.ticketbox.data.remote.dto.MemberRepaymentProposalRejectRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.MemberRepaymentProposalDto = unsupported()
    override suspend fun repaymentDrafts(
        status: String?,
    ): com.ticketbox.data.remote.dto.RepaymentDraftListResponseDto = unsupported()
    override suspend fun createRepaymentDraft(
        request: com.ticketbox.data.remote.dto.RepaymentDraftCreateRequestDto,
    ): com.ticketbox.data.remote.dto.RepaymentDraftDto = unsupported()
    override suspend fun confirmRepaymentDraft(
        publicId: String,
        request: com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto,
        idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.RepaymentDraftDto = unsupported()
    override suspend fun dismissRepaymentDraft(
        publicId: String,
        request: com.ticketbox.data.remote.dto.RepaymentDraftDismissRequestDto,
    ): com.ticketbox.data.remote.dto.RepaymentDraftDto = unsupported()
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
    override suspend fun updateIncomePlan(publicId: String, request: com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto, idempotencyKey: String?): com.ticketbox.data.remote.dto.IncomePlanDto = unsupported()
    override suspend fun archiveIncomePlan(publicId: String, request: com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto): com.ticketbox.data.remote.dto.IncomePlanDto = unsupported()
    override suspend fun restoreIncomePlan(publicId: String, request: com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto): com.ticketbox.data.remote.dto.IncomePlanDto = unsupported()
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
    override suspend fun pauseRecurringItem(publicId: String, request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest): RecurringItemDto = unsupported()
    override suspend fun resumeRecurringItem(publicId: String, request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest): RecurringItemDto = unsupported()
    override suspend fun archiveRecurringItem(publicId: String): RecurringItemDto = unsupported()
    override suspend fun dataQualitySummary(): com.ticketbox.data.remote.dto.DataQualitySummaryDto = unsupported()

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

    override suspend fun ledgerDevices(
        ledgerId: String,
    ): com.ticketbox.data.remote.dto.MyDeviceListResponseDto = unsupported()

    override suspend fun renameLedgerDevice(
        ledgerId: String,
        publicId: String,
        request: com.ticketbox.data.remote.dto.DeviceRenameRequestDto,
    ): com.ticketbox.data.remote.dto.MyDeviceDto = unsupported()

    override suspend fun revokeLedgerDevice(
        ledgerId: String,
        publicId: String,
    ): com.ticketbox.data.remote.dto.MyDeviceDto = unsupported()

    override suspend fun createLedgerDevicePairingCode(
        ledgerId: String,
        request: com.ticketbox.data.remote.dto.PairingCodeCreateRequestDto,
    ): com.ticketbox.data.remote.dto.PairingCodeResponseDto = unsupported()

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
        rowVersion = 1L,
    )

    private fun expenseItemsResponse(): ExpenseItemsResponseDto = ExpenseItemsResponseDto(
        expenseId = 9,
        rowVersion = 1L,
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
        rowVersion = 1L,
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
            rowVersion = 1L,
            confirmedAt = "2026-05-09T08:12:40Z",
            rejectedAt = null,
        )
    }
}
