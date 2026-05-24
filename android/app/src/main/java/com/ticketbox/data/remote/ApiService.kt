package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
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
import com.ticketbox.data.remote.dto.LedgerCreateRequestDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberRoleUpdateRequestDto
import com.ticketbox.data.remote.dto.LedgerSwitchResponseDto
import com.ticketbox.data.remote.dto.InvitationAcceptRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewRequestDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.NotificationDraftRequestDto
import com.ticketbox.data.remote.dto.OwnerTransferResponseDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.PairRequestDto
import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringCandidatesResponseDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.RefreshSessionResponseDto
import com.ticketbox.data.remote.dto.DataQualitySummaryDto
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.DashboardCardsUpdateRequestDto
import com.ticketbox.data.remote.dto.PairResponseDto
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
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.Part
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.PUT
import retrofit2.http.Query
import retrofit2.http.Streaming

interface ApiService {
    @GET("api/auth/check")
    suspend fun checkAuth(): AuthCheckDto

    @POST("api/auth/pair")
    suspend fun pairDevice(@Body request: PairRequestDto): PairResponseDto

    @POST("api/auth/refresh")
    suspend fun refreshSession(): RefreshSessionResponseDto

    @GET("api/expenses/pending")
    suspend fun pendingExpenses(): List<ExpenseDto>

    @GET("api/expenses/confirmed")
    suspend fun confirmedExpenses(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 50,
        @Query("month") month: String? = null,
        @Query("category") category: String? = null,
        @Query("tag") tag: String? = null,
        @Query("timezone") timezone: String? = null,
    ): PaginatedExpensesDto

    @GET("api/expenses/categories")
    suspend fun categories(): CategoriesDto

    @GET("api/expenses/tags")
    suspend fun tags(): TagsDto

    @GET("api/expenses/months")
    suspend fun months(@Query("timezone") timezone: String? = null): MonthsDto

    @GET("api/expenses/export.csv")
    @Streaming
    suspend fun exportCsv(
        @Query("month") month: String? = null,
        @Query("category") category: String? = null,
        @Query("tag") tag: String? = null,
        @Query("timezone") timezone: String? = null,
    ): Response<ResponseBody>

    @POST("api/expenses/manual")
    suspend fun createManualExpense(@Body request: ExpenseUpdateRequest): ExpenseDto

    @POST("api/expenses/notification-drafts")
    suspend fun createNotificationDraft(@Body request: NotificationDraftRequestDto): ExpenseDto

    @Multipart
    @POST("api/app/upload-screenshot")
    suspend fun uploadScreenshot(
        @Part file: MultipartBody.Part,
        @Header("X-Timezone") timezone: String? = null,
    ): UploadResponseDto

    @GET("api/expenses/{id}")
    suspend fun expense(@Path("id") id: Long): ExpenseDto

    @PATCH("api/expenses/{id}")
    suspend fun updateExpense(
        @Path("id") id: Long,
        @Body request: ExpenseUpdateRequest,
    ): ExpenseDto

    @GET("api/expenses/{id}/items")
    suspend fun expenseItems(@Path("id") id: Long): ExpenseItemsResponseDto

    @PUT("api/expenses/{id}/items")
    suspend fun replaceExpenseItems(
        @Path("id") id: Long,
        @Body request: ExpenseItemReplaceRequestDto,
    ): ExpenseItemsResponseDto

    @POST("api/expenses/{id}/items/acknowledge-mismatch")
    suspend fun acknowledgeExpenseItemsMismatch(
        @Path("id") id: Long,
    ): ExpenseItemsResponseDto

    // ADR-0029 bill split workflow
    @POST("api/expenses/{id}/split-invite")
    suspend fun createBillSplitInvitation(
        @Path("id") id: Long,
        @Body request: com.ticketbox.data.remote.dto.BillSplitInviteRequestDto,
    ): com.ticketbox.data.remote.dto.BillSplitSentDto

    @GET("api/bill-splits/inbox")
    suspend fun listBillSplitInbox(): com.ticketbox.data.remote.dto.BillSplitInboxListResponseDto

    @GET("api/bill-splits/sent")
    suspend fun listBillSplitSent(): com.ticketbox.data.remote.dto.BillSplitSentListResponseDto

    @POST("api/bill-splits/{publicId}/accept")
    suspend fun acceptBillSplitInvitation(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.BillSplitAcceptRequestDto,
    ): com.ticketbox.data.remote.dto.BillSplitInboxDto

    @POST("api/bill-splits/{publicId}/reject")
    suspend fun rejectBillSplitInvitation(
        @Path("publicId") publicId: String,
    ): com.ticketbox.data.remote.dto.BillSplitInboxDto

    @POST("api/bill-splits/{publicId}/cancel")
    suspend fun cancelBillSplitInvitation(
        @Path("publicId") publicId: String,
    ): com.ticketbox.data.remote.dto.BillSplitSentDto

    @GET("api/expenses/{id}/splits")
    suspend fun expenseSplits(@Path("id") id: Long): ExpenseSplitsResponseDto

    @PUT("api/expenses/{id}/splits")
    suspend fun replaceExpenseSplits(
        @Path("id") id: Long,
        @Body request: ExpenseSplitReplaceRequestDto,
    ): ExpenseSplitsResponseDto

    @POST("api/expenses/{id}/confirm")
    suspend fun confirmExpense(@Path("id") id: Long): ExpenseDto

    @POST("api/expenses/{id}/reject")
    suspend fun rejectExpense(@Path("id") id: Long): ExpenseDto

    @POST("api/expenses/{id}/ocr/retry")
    suspend fun retryOcr(@Path("id") id: Long): ExpenseDto

    @POST("api/expenses/{id}/suggestions/{decisionPublicId}/accept")
    suspend fun acceptPendingSuggestion(
        @Path("id") id: Long,
        @Path("decisionPublicId") decisionPublicId: String,
    ): StatusDto

    @POST("api/expenses/{id}/suggestions/{decisionPublicId}/reject")
    suspend fun rejectPendingSuggestion(
        @Path("id") id: Long,
        @Path("decisionPublicId") decisionPublicId: String,
    ): StatusDto

    @POST("api/expenses/{id}/mark-not-duplicate")
    suspend fun markNotDuplicate(@Path("id") id: Long): ExpenseDto

    @GET("api/expenses/{id}/image")
    @Streaming
    suspend fun expenseImage(@Path("id") id: Long): Response<ResponseBody>

    @GET("api/expenses/{id}/thumbnail")
    @Streaming
    suspend fun expenseThumbnail(@Path("id") id: Long): Response<ResponseBody>

    @GET("api/duplicates")
    suspend fun duplicates(): List<ExpenseDto>

    @GET("api/rules/categories")
    suspend fun categoryRules(): List<CategoryRuleDto>

    @POST("api/rules/categories")
    suspend fun createCategoryRule(@Body request: CategoryRuleRequest): CategoryRuleDto

    @PATCH("api/rules/categories/{id}")
    suspend fun updateCategoryRule(
        @Path("id") id: Long,
        @Body request: CategoryRuleRequest,
    ): CategoryRuleDto

    @DELETE("api/rules/categories/{id}")
    suspend fun deleteCategoryRule(@Path("id") id: Long): StatusDto

    @GET("api/merchants/aliases")
    suspend fun merchantAliases(): MerchantAliasListDto

    @POST("api/merchants/aliases")
    suspend fun createMerchantAlias(@Body request: MerchantAliasRequest): MerchantAliasDto

    @PATCH("api/merchants/aliases/{publicId}")
    suspend fun updateMerchantAlias(
        @Path("publicId") publicId: String,
        @Body request: MerchantAliasRequest,
    ): MerchantAliasDto

    @DELETE("api/merchants/aliases/{publicId}")
    suspend fun deleteMerchantAlias(@Path("publicId") publicId: String): StatusDto

    @GET("api/rules/applications")
    suspend fun ruleApplications(
        @Query("limit") limit: Int = 20,
    ): RuleApplicationListDto

    @POST("api/rules/applications/{publicId}/rollback")
    suspend fun rollbackRuleApplication(
        @Path("publicId") publicId: String,
    ): RuleApplicationRollbackDto

    @POST("api/rules/apply-confirmed")
    suspend fun applyConfirmedRules(
        @Body request: RuleApplyConfirmedRequestDto = RuleApplyConfirmedRequestDto(),
        @Query("limit") limit: Int = 20,
        @Query("max_scan") maxScan: Int = 500,
    ): RuleApplyConfirmedResponseDto

    @GET("api/settings/server")
    suspend fun serverSettings(): ServerSettingsDto

    @GET("api/stats/monthly")
    suspend fun monthlyStats(
        @Query("month") month: String? = null,
        @Query("tag") tag: String? = null,
        @Query("timezone") timezone: String? = null,
    ): MonthlyStatsDto

    @GET("api/stats/lifestyle")
    suspend fun lifestyleStats(
        @Query("month") month: String? = null,
        @Query("timezone") timezone: String? = null,
    ): LifestyleStatsDto

    @GET("api/reports/overview")
    suspend fun reportsOverview(
        @Query("month") month: String? = null,
        @Query("granularity") granularity: String = "day",
        @Query("top_n") topN: Int = 8,
        @Query("merchant_category") merchantCategory: String? = null,
        @Query("ranking_metric") rankingMetric: String = "amount",
        @Query("timezone") timezone: String? = null,
    ): ReportsOverviewDto

    @GET("api/reports/overview.csv")
    @Streaming
    suspend fun reportsOverviewCsv(
        @Query("month") month: String? = null,
        @Query("granularity") granularity: String = "day",
        @Query("top_n") topN: Int = 8,
        @Query("merchant_category") merchantCategory: String? = null,
        @Query("ranking_metric") rankingMetric: String = "amount",
        @Query("timezone") timezone: String? = null,
    ): Response<ResponseBody>

    @GET("api/goals")
    suspend fun goals(
        @Query("month") month: String? = null,
        @Query("include_archived") includeArchived: Boolean = false,
        @Query("timezone") timezone: String? = null,
    ): GoalListResponseDto

    @POST("api/goals")
    suspend fun createGoal(
        @Body request: GoalCreateRequestDto,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    @GET("api/goals/{publicId}")
    suspend fun goal(
        @Path("publicId") publicId: String,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    @PATCH("api/goals/{publicId}")
    suspend fun updateGoal(
        @Path("publicId") publicId: String,
        @Body request: GoalUpdateRequestDto,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    @POST("api/goals/{publicId}/archive")
    suspend fun archiveGoal(
        @Path("publicId") publicId: String,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    @GET("api/dashboard/cards")
    suspend fun dashboardCards(
        @Query("surface") surface: String = "android",
    ): DashboardCardsResponseDto

    @PUT("api/dashboard/cards")
    suspend fun updateDashboardCards(
        @Body request: DashboardCardsUpdateRequestDto,
        @Query("surface") surface: String = "android",
    ): DashboardCardsResponseDto

    @GET("api/budgets/monthly")
    suspend fun monthlyBudget(
        @Query("month") month: String,
        @Query("timezone") timezone: String? = null,
    ): BudgetMonthlyDto

    @PUT("api/budgets/monthly/{month}")
    suspend fun updateMonthlyBudget(
        @Path("month") month: String,
        @Body request: BudgetMonthlyUpdateRequestDto,
        @Query("timezone") timezone: String? = null,
    ): BudgetMonthlyDto

    // v1.1 income plans (PR-7 routes) + budget advisor (PR-7 + PR-8)
    @GET("api/income-plans")
    suspend fun listIncomePlans(
        @Query("status") status: String = "active",
    ): com.ticketbox.data.remote.dto.IncomePlanListResponseDto

    @POST("api/income-plans")
    suspend fun createIncomePlan(
        @Body request: com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto,
    ): com.ticketbox.data.remote.dto.IncomePlanDto

    @PATCH("api/income-plans/{publicId}")
    suspend fun updateIncomePlan(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto,
    ): com.ticketbox.data.remote.dto.IncomePlanDto

    @DELETE("api/income-plans/{publicId}")
    suspend fun archiveIncomePlan(
        @Path("publicId") publicId: String,
    ): com.ticketbox.data.remote.dto.IncomePlanDto

    @POST("api/income-plans/{publicId}/restore")
    suspend fun restoreIncomePlan(
        @Path("publicId") publicId: String,
    ): com.ticketbox.data.remote.dto.IncomePlanDto

    @GET("api/budget/discretionary")
    suspend fun budgetDiscretionary(
        @Query("savings_target_cents") savingsTargetCents: Long = 0L,
        @Query("reserved_buffer_cents") reservedBufferCents: Long = 0L,
    ): com.ticketbox.data.remote.dto.DiscretionaryResponseDto

    @POST("api/budget/advise")
    suspend fun budgetAdvise(
        @Body request: com.ticketbox.data.remote.dto.BudgetAdviseRequestDto,
    ): com.ticketbox.data.remote.dto.BudgetAdviseResponseDto

    @GET("api/insights/recurring-candidates")
    suspend fun recurringCandidates(
        @Query("timezone") timezone: String? = null,
    ): RecurringCandidatesResponseDto

    @GET("api/recurring/items")
    suspend fun recurringItems(
        @Query("status") status: String? = null,
        @Query("include_archived") includeArchived: Boolean = false,
        @Query("month") month: String? = null,
        @Query("timezone") timezone: String? = null,
    ): RecurringItemListResponseDto

    @POST("api/recurring/from-candidate")
    suspend fun confirmRecurringCandidate(
        @Body request: RecurringCandidateConfirmRequestDto,
        @Query("timezone") timezone: String? = null,
    ): RecurringItemDto

    @GET("api/recurring/items/{publicId}")
    suspend fun recurringItem(
        @Path("publicId") publicId: String,
        @Query("month") month: String? = null,
        @Query("timezone") timezone: String? = null,
    ): RecurringItemDto

    @POST("api/recurring/items/{publicId}/pause")
    suspend fun pauseRecurringItem(@Path("publicId") publicId: String): RecurringItemDto

    @POST("api/recurring/items/{publicId}/resume")
    suspend fun resumeRecurringItem(@Path("publicId") publicId: String): RecurringItemDto

    @POST("api/recurring/items/{publicId}/archive")
    suspend fun archiveRecurringItem(@Path("publicId") publicId: String): RecurringItemDto

    @GET("api/insights/data-quality")
    suspend fun dataQualitySummary(): DataQualitySummaryDto

    @GET("api/ledgers")
    suspend fun listLedgers(): LedgerListResponseDto

    @POST("api/ledgers")
    suspend fun createLedger(@Body request: LedgerCreateRequestDto): com.ticketbox.data.remote.dto.LedgerDto

    @POST("api/ledgers/{ledgerId}/switch")
    suspend fun switchLedger(@Path("ledgerId") ledgerId: String): LedgerSwitchResponseDto

    @GET("api/ledgers/{ledgerId}/members")
    suspend fun ledgerMembers(@Path("ledgerId") ledgerId: String): LedgerMemberListResponseDto

    @GET("api/ledgers/{ledgerId}/audit")
    suspend fun ledgerAudit(
        @Path("ledgerId") ledgerId: String,
        @Query("limit") limit: Int = 100,
    ): LedgerAuditListResponseDto

    @POST("api/ledgers/{ledgerId}/members/{memberId}/role")
    suspend fun updateLedgerMemberRole(
        @Path("ledgerId") ledgerId: String,
        @Path("memberId") memberId: Long,
        @Body request: LedgerMemberRoleUpdateRequestDto,
    ): LedgerMemberDto

    @POST("api/ledgers/{ledgerId}/members/{memberId}/disable")
    suspend fun disableLedgerMember(
        @Path("ledgerId") ledgerId: String,
        @Path("memberId") memberId: Long,
    ): LedgerMemberDto

    @POST("api/ledgers/{ledgerId}/members/{memberId}/transfer-owner")
    suspend fun transferLedgerOwner(
        @Path("ledgerId") ledgerId: String,
        @Path("memberId") memberId: Long,
    ): OwnerTransferResponseDto

    @POST("api/invitations/preview")
    suspend fun previewInvitation(
        @Body request: InvitationPreviewRequestDto,
    ): InvitationPreviewResponseDto

    @POST("api/invitations/accept")
    suspend fun acceptInvitation(
        @Body request: InvitationAcceptRequestDto,
    ): InvitationAcceptResponseDto

    // v0.10: cross-surface UI preferences (theme sync etc.). See docs/V0_9_DESIGN_TOKEN_REFERENCE.md.
    @GET("api/me/ui-preferences")
    suspend fun getUiPreferences(): Response<UserUiPreferencesDto>

    @PUT("api/me/ui-preferences")
    suspend fun putUiPreferences(@Body request: UserUiPreferencesUpdateRequestDto): Response<UserUiPreferencesDto>

    // ADR-0030 background tasks
    @GET("api/tasks")
    suspend fun listBackgroundTasks(): com.ticketbox.data.remote.dto.BackgroundTaskListResponseDto

    @GET("api/tasks/{publicId}")
    suspend fun getBackgroundTask(
        @Path("publicId") publicId: String,
    ): com.ticketbox.data.remote.dto.BackgroundTaskDto

    @POST("api/tasks/{publicId}/cancel")
    suspend fun cancelBackgroundTask(
        @Path("publicId") publicId: String,
    ): com.ticketbox.data.remote.dto.BackgroundTaskDto
}
