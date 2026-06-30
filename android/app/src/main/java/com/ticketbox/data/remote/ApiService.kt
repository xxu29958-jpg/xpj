package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.data.remote.dto.DebtBillParseResponseDto
import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtForgiveCreateRequestDto
import com.ticketbox.data.remote.dto.DebtGoalIntegrityReviewRequestDto
import com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto
import com.ticketbox.data.remote.dto.DebtGoalTargetDateRequestDto
import com.ticketbox.data.remote.dto.DebtKindSetRequestDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.DebtVoidCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseRepaymentDraftCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.LedgerCreateRequestDto
import com.ticketbox.data.remote.dto.DeviceRenameRequestDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberRoleUpdateRequestDto
import com.ticketbox.data.remote.dto.LedgerSwitchResponseDto
import com.ticketbox.data.remote.dto.MyDeviceDto
import com.ticketbox.data.remote.dto.MyDeviceListResponseDto
import com.ticketbox.data.remote.dto.PairingCodeCreateRequestDto
import com.ticketbox.data.remote.dto.PairingCodeResponseDto
import com.ticketbox.data.remote.dto.InvitationAcceptRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationCreateRequestDto
import com.ticketbox.data.remote.dto.InvitationCreateResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewRequestDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalConfirmRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalCreateRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalListResponseDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalRejectRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalWithdrawRequestDto
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogCreateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDeleteRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogListDto
import com.ticketbox.data.remote.dto.MerchantCatalogUpdateRequest
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
import com.ticketbox.data.remote.dto.RecycleBinListResponseDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreRequestDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreResponseDto
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
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
import com.ticketbox.data.remote.dto.StatusPrivateDto
import com.ticketbox.data.remote.dto.TagDeleteRequest
import com.ticketbox.data.remote.dto.TagDetailDto
import com.ticketbox.data.remote.dto.TagManagementListDto
import com.ticketbox.data.remote.dto.TagMergeRequest
import com.ticketbox.data.remote.dto.TagMutationDto
import com.ticketbox.data.remote.dto.TagRenameRequest
import com.ticketbox.data.remote.dto.TagUndoDto
import com.ticketbox.data.remote.dto.TagUndoRequest
import com.ticketbox.data.remote.dto.TagsDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.HTTP
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

    /** server 级私有状态(备份链健康,轴6 备份超龄通知数据源);只要 app token,与 ledger 无关。 */
    @GET("api/status/private")
    suspend fun privateStatus(): StatusPrivateDto

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
    suspend fun createManualExpense(@Body request: ExpenseManualCreateRequestDto): ExpenseDto

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
        // issue #65 slice 3: server-id-or-``local:{client_ref}`` string ref.
        @Path("id") id: String,
        @Body request: ExpenseUpdateRequest,
        // ADR-0042: intent-time idempotency key. A committed-but-unseen replay
        // (direct PATCH commits server-side but the response is lost, then the
        // outbox replays) carries the SAME key so the server HITs and returns
        // the canonical row instead of false-409ing on the now-stale
        // expected_row_version. Nullable for Retrofit ergonomics (a null value
        // is omitted from the request); the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    @GET("api/expenses/{id}/items")
    suspend fun expenseItems(@Path("id") id: Long): ExpenseItemsResponseDto

    @PUT("api/expenses/{id}/items")
    suspend fun replaceExpenseItems(
        @Path("id") id: String,
        @Body request: ExpenseItemReplaceRequestDto,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseItemsResponseDto

    @POST("api/expenses/{id}/items/acknowledge-mismatch")
    suspend fun acknowledgeExpenseItemsMismatch(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseItemsResponseDto

    // ADR-0029 bill split workflow
    @POST("api/expenses/{id}/split-invite")
    suspend fun createBillSplitInvitation(
        @Path("id") id: Long,
        @Body request: com.ticketbox.data.remote.dto.BillSplitInviteRequestDto,
    ): com.ticketbox.data.remote.dto.BillSplitSentDto

    @GET("api/bill-splits/inbox")
    suspend fun listBillSplitInbox(
        @Query("status") status: String? = null,
    ): com.ticketbox.data.remote.dto.BillSplitInboxListResponseDto

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
        @Path("id") id: String,
        @Body request: ExpenseSplitReplaceRequestDto,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseSplitsResponseDto

    @POST("api/expenses/{id}/confirm")
    suspend fun confirmExpense(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    @POST("api/expenses/{id}/reject")
    suspend fun rejectExpense(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    // ADR-0038 undo: restore a recently-rejected expense (5-min window). No
    // request body — the caller just rejected the row and there's near-zero
    // contention inside the window. 404 ``expense_not_found`` once the window
    // closes / row was never rejected / cross-tenant — same collapse semantic
    // as merchant_alias / category_rule undo. Online-only: an offline Queued
    // reject has nothing to restore via the API (its rejection lives in the
    // outbox, not the server); UI should only show the undo affordance after
    // an ExpenseStateOutcome.Synced reject.
    // ADR-0038 PR-A: undo now carries expected_row_version — rejects stale
    // /undo from a banner whose row has been re-rejected since the banner
    // was shown. Without it a cached banner could un-do a NEW intentional
    // reject.
    @POST("api/expenses/{id}/undo")
    suspend fun undoExpense(
        @Path("id") id: Long,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
    ): ExpenseDto

    @POST("api/expenses/{id}/ocr/retry")
    suspend fun retryOcr(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    // ADR-0042 Slice E-2: client supplies ``raw_text`` and the server parses it
    // into the draft fields (DISTINCT from retryOcr, which re-runs the server OCR
    // provider on the stored image). Body-carrying like replaceExpenseItems.
    @POST("api/expenses/{id}/recognize-text")
    suspend fun recognizeText(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

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
    suspend fun markNotDuplicate(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    @POST("api/expenses/{id}/repayment-draft")
    suspend fun createRepaymentDraftFromExpense(
        @Path("id") id: String,
        @Body request: ExpenseRepaymentDraftCreateRequestDto,
    ): RepaymentDraftDto

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
        @Body request: CategoryRuleUpdateRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): CategoryRuleDto

    @HTTP(method = "DELETE", path = "api/rules/categories/{id}", hasBody = true)
    suspend fun deleteCategoryRule(
        @Path("id") id: Long,
        @Body request: CategoryRuleDeleteRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): StatusDto

    // ADR-0038 undo: restore a soft-deleted category rule (no body / token — it
    // restores the row the caller just deleted). Returns the restored rule.
    @POST("api/rules/categories/{id}/undo")
    suspend fun undoCategoryRule(@Path("id") id: Long): CategoryRuleDto

    @GET("api/merchants/catalog")
    suspend fun merchantCatalog(
        @Query("include_hidden") includeHidden: Boolean = true,
    ): MerchantCatalogListDto

    @POST("api/merchants/catalog")
    suspend fun createMerchantCatalog(@Body request: MerchantCatalogCreateRequest): MerchantCatalogDto

    @PATCH("api/merchants/catalog/{publicId}")
    suspend fun updateMerchantCatalog(
        @Path("publicId") publicId: String,
        @Body request: MerchantCatalogUpdateRequest,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MerchantCatalogDto

    @HTTP(method = "DELETE", path = "api/merchants/catalog/{publicId}", hasBody = true)
    suspend fun deleteMerchantCatalog(
        @Path("publicId") publicId: String,
        @Body request: MerchantCatalogDeleteRequest,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MerchantCatalogDto

    @GET("api/merchants/aliases")
    suspend fun merchantAliases(): MerchantAliasListDto

    @POST("api/merchants/aliases")
    suspend fun createMerchantAlias(@Body request: MerchantAliasRequest): MerchantAliasDto

    @PATCH("api/merchants/aliases/{publicId}")
    suspend fun updateMerchantAlias(
        @Path("publicId") publicId: String,
        @Body request: MerchantAliasUpdateRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MerchantAliasDto

    @HTTP(method = "DELETE", path = "api/merchants/aliases/{publicId}", hasBody = true)
    suspend fun deleteMerchantAlias(
        @Path("publicId") publicId: String,
        @Body request: MerchantAliasDeleteRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): StatusDto

    // ADR-0038 undo: restore a soft-deleted alias (no body / token — it
    // restores the row the caller just deleted). Returns the restored alias.
    @POST("api/merchants/aliases/{publicId}/undo")
    suspend fun undoMerchantAlias(@Path("publicId") publicId: String): MerchantAliasDto

    // ADR-0043 slice C — tag management (online-only mutate surface, 契约 7):
    // every mutation carries expected_row_version in its body; NONE declares an
    // Idempotency-Key header (declaring it would route through the replay path).
    @GET("api/tags")
    suspend fun listManagedTags(): TagManagementListDto

    @POST("api/tags/{publicId}/rename")
    suspend fun renameTag(
        @Path("publicId") publicId: String,
        @Body request: TagRenameRequest,
    ): TagDetailDto

    @POST("api/tags/{publicId}/delete")
    suspend fun deleteTag(
        @Path("publicId") publicId: String,
        @Body request: TagDeleteRequest,
    ): TagMutationDto

    @POST("api/tags/{publicId}/merge")
    suspend fun mergeTag(
        @Path("publicId") publicId: String,
        @Body request: TagMergeRequest,
    ): TagMutationDto

    @POST("api/tags/mutations/{mutationPublicId}/undo")
    suspend fun undoTagMutation(
        @Path("mutationPublicId") mutationPublicId: String,
        @Body request: TagUndoRequest,
    ): TagUndoDto

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
        // ADR-0049 §6 (slice 7): "debt_repayment" lists the (month-less) debt goals;
        // null/omitted keeps the historical spending_limit month-scoped behaviour.
        @Query("goal_type") goalType: String? = null,
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
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    @POST("api/goals/{publicId}/archive")
    suspend fun archiveGoal(
        @Path("publicId") publicId: String,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    // ADR-0049 §6 (slice 7): replace a debt_repayment goal's linked Debt set →
    // a new goal version. OCC token in the body + ADR-0042 intent-time idempotency
    // key in the header (mirrors updateGoal). Returns the fold-after GoalDto.
    @POST("api/goals/{publicId}/debt-links")
    suspend fun replaceGoalDebtLinks(
        @Path("publicId") publicId: String,
        @Body request: DebtGoalLinksReplaceRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    // ADR-0049 §6/F13 (slice 7): acknowledge ("keep for audit") an achieved debt
    // goal version whose linked set carries a debt-voided Debt — clears needs_review
    // for the current version. OCC token in the body + idempotency key in the header.
    @POST("api/goals/{publicId}/integrity-review/acknowledge")
    suspend fun acknowledgeGoalIntegrityReview(
        @Path("publicId") publicId: String,
        @Body request: DebtGoalIntegrityReviewRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    // ADR-0049 §7.0 / 8e-6c (slice 8e-6c): set or clear a debt_repayment goal's payoff deadline.
    // OCC token in the body (bumps row_version only, never goal_version) + idempotency key in the
    // header (mirrors the link-replace / integrity-review setters). Returns the fold-after GoalDto.
    @POST("api/goals/{publicId}/target-date")
    suspend fun setGoalTargetDate(
        @Path("publicId") publicId: String,
        @Body request: DebtGoalTargetDateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    // ADR-0049 §2 (slice 8): Debt entity surface. The list is ledger-scoped via the session
    // token (no query params); create accepts an external/manual Debt and carries the
    // ADR-0042 intent-time idempotency key (nullable for Retrofit ergonomics — the repository
    // always supplies a UUID). Both routes return the server-derived fold shape.
    @GET("api/debts")
    suspend fun debts(): DebtListResponseDto

    // ADR-0049 P3b / ⑤c (slice ⑤c-2) creditor discovery: the ACCOUNT-scoped (cross-ledger) list of
    // member Debts this account is the creditor of — "money owed to me" that the ledger-scoped
    // GET /api/debts can't surface (a bill_split member Debt lives in the debtor's ledger). Every row
    // is a member receivable (viewer_is_debtor=false), ledger_id redacted to null (§5.2). Read-only.
    @GET("api/debts/receivables")
    suspend fun debtReceivables(): DebtListResponseDto

    @POST("api/debts")
    suspend fun createDebt(
        @Body request: DebtCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    // ADR-0049 §D: transient debt-bill OCR/vision parser. Multipart image in, suggestion fields
    // out; no Debt is created until the user confirms the normal create form.
    @Multipart
    @POST("api/debts/parse-bill")
    suspend fun parseDebtBill(@Part file: MultipartBody.Part): DebtBillParseResponseDto

    // ADR-0049 §2 (slice 8c): one Debt's server-derived fold (for the detail screen). 404
    // debt_not_found; a cross-ledger participant gets the redacted shell (ledger_id null, §5.2).
    @GET("api/debts/{publicId}")
    suspend fun debt(@Path("publicId") publicId: String): DebtDto

    // ADR-0049 §3 (slice 8c) direct fact writes for external/manual Debt (member/bill_split go
    // through the slice-3 proposal flow, §5.2 → 409 here). Each carries expected_row_version in the
    // body (§2.1 stale-intent fence + §3.6 fingerprint) and an ADR-0042 intent-time idempotency key
    // in the header (nullable for Retrofit ergonomics — the repository always supplies a UUID). The
    // repayment route returns RepaymentCreateResponse (a DebtResponse superset); Moshi keeps the
    // shared fold fields and drops the unused repayment_public_id, so DebtDto is the right shape.
    @POST("api/debts/{publicId}/repayments")
    suspend fun recordDebtRepayment(
        @Path("publicId") publicId: String,
        @Body request: RepaymentCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    @POST("api/debts/{publicId}/adjustments")
    suspend fun recordDebtAdjustment(
        @Path("publicId") publicId: String,
        @Body request: DebtAdjustmentCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    @POST("api/debts/{publicId}/void")
    suspend fun voidDebt(
        @Path("publicId") publicId: String,
        @Body request: DebtVoidCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    // ADR-0049 §7.0 / 8e-6e: set or correct an existing external Debt's repayment-rhythm
    // classification (debt_kind). OCC token in the body (bumps row_version; NOT fold-changing —
    // it gates only the payoff projection, not remaining/paid/status) + an ADR-0042 intent-time
    // idempotency key in the header (nullable for Retrofit ergonomics — the repository always
    // supplies a UUID). Returns the re-serialized fold (DebtResponse → DebtDto) so the detail
    // screen swaps in the fresh row_version + debt_kind.
    @POST("api/debts/{publicId}/kind")
    suspend fun setDebtKind(
        @Path("publicId") publicId: String,
        @Body request: DebtKindSetRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    // ADR-0049 §3.2 (slice 8d) member repayment proposals. The two parties of a member Debt can
    // live in different ledgers (a bill_split Debt is owned by the receiver, sender = cross-ledger
    // creditor), so these routes are participant-scoped (§5.2), not ledger-scoped. The debtor
    // proposes "I paid" / withdraws; the creditor confirms (full or partial) / rejects. Confirm is
    // fold-changing → it carries expected_row_version in the body + replies with the fold-after
    // DebtResponse (DebtDto); the other writes reply with the proposal's own response. Every write
    // carries an ADR-0042 intent-time idempotency key (nullable for Retrofit ergonomics — the
    // repository always supplies a UUID). The list GET is read-only (no key).
    @GET("api/debts/{publicId}/repayment-proposals")
    suspend fun repaymentProposals(
        @Path("publicId") publicId: String,
    ): MemberRepaymentProposalListResponseDto

    @POST("api/debts/{publicId}/repayment-proposals")
    suspend fun createRepaymentProposal(
        @Path("publicId") publicId: String,
        @Body request: MemberRepaymentProposalCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MemberRepaymentProposalDto

    @POST("api/debts/{publicId}/repayment-proposals/{proposalPublicId}/withdraw")
    suspend fun withdrawRepaymentProposal(
        @Path("publicId") publicId: String,
        @Path("proposalPublicId") proposalPublicId: String,
        @Body request: MemberRepaymentProposalWithdrawRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MemberRepaymentProposalDto

    @POST("api/debts/{publicId}/repayment-proposals/{proposalPublicId}/confirm")
    suspend fun confirmRepaymentProposal(
        @Path("publicId") publicId: String,
        @Path("proposalPublicId") proposalPublicId: String,
        @Body request: MemberRepaymentProposalConfirmRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    @POST("api/debts/{publicId}/repayment-proposals/{proposalPublicId}/reject")
    suspend fun rejectRepaymentProposal(
        @Path("publicId") publicId: String,
        @Path("proposalPublicId") proposalPublicId: String,
        @Body request: MemberRepaymentProposalRejectRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MemberRepaymentProposalDto

    // ADR-0049 §3.7 / §4 (slice 8e-3): the creditor forgives a member Debt's remaining
    // ("算了，不用还了"). One-sided (no debtor confirmation), member + creditor only (the server
    // 403s a debtor / 409s an external Debt). Fold-changing → it carries expected_row_version in the
    // body + an ADR-0042 intent-time idempotency key in the header, and replies with the fold-after
    // DebtResponse (DebtDto: cleared + is_forgiven). §5.2: a cross-ledger creditor gets the shell.
    @POST("api/debts/{publicId}/forgive")
    suspend fun forgiveDebt(
        @Path("publicId") publicId: String,
        @Body request: DebtForgiveCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    // ADR-0049 §杠杆③ (slice 3a): NLS repayment-capture inbox. The list is ledger-scoped via the
    // session token (default status=pending). Create posts one NLS-captured repayment as a PENDING
    // draft (never auto-records — §8); it is content+identity deduped server-side, so it carries no
    // OCC token (its safe-replay rests on the dedup key) — the repository does not mint an
    // Idempotency-Key for it. Confirm records ONE Repayment against the chosen open external/manual
    // Debt → fold-changing, so it carries expected_row_version in the body + an ADR-0042 intent-time
    // idempotency key in the header (nullable for Retrofit ergonomics — the repository supplies a
    // UUID). Dismiss latches the draft dismissed (no token). All three resolution routes return the
    // re-serialized RepaymentDraftResponse.
    @GET("api/repayment-drafts")
    suspend fun repaymentDrafts(
        @Query("status") status: String? = null,
    ): com.ticketbox.data.remote.dto.RepaymentDraftListResponseDto

    @POST("api/repayment-drafts")
    suspend fun createRepaymentDraft(
        @Body request: com.ticketbox.data.remote.dto.RepaymentDraftCreateRequestDto,
    ): com.ticketbox.data.remote.dto.RepaymentDraftDto

    @POST("api/repayment-drafts/{publicId}/confirm")
    suspend fun confirmRepaymentDraft(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.RepaymentDraftDto

    @POST("api/repayment-drafts/{publicId}/dismiss")
    suspend fun dismissRepaymentDraft(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.RepaymentDraftDismissRequestDto,
    ): com.ticketbox.data.remote.dto.RepaymentDraftDto

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
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.IncomePlanDto

    @HTTP(method = "DELETE", path = "api/income-plans/{publicId}", hasBody = true)
    suspend fun archiveIncomePlan(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto,
    ): com.ticketbox.data.remote.dto.IncomePlanDto

    @POST("api/income-plans/{publicId}/restore")
    suspend fun restoreIncomePlan(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto,
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
    suspend fun pauseRecurringItem(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest,
    ): RecurringItemDto

    @POST("api/recurring/items/{publicId}/resume")
    suspend fun resumeRecurringItem(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest,
    ): RecurringItemDto

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

    /** 轴7 发邀请(owner 级):invite_token 明文只在本响应出现一次。 */
    @POST("api/ledgers/{ledgerId}/invitations")
    suspend fun createInvitation(
        @Path("ledgerId") ledgerId: String,
        @Body request: InvitationCreateRequestDto,
    ): InvitationCreateResponseDto

    @POST("api/invitations/preview")
    suspend fun previewInvitation(
        @Body request: InvitationPreviewRequestDto,
    ): InvitationPreviewResponseDto

    @POST("api/invitations/accept")
    suspend fun acceptInvitation(
        @Body request: InvitationAcceptRequestDto,
    ): InvitationAcceptResponseDto

    // issue #65 slice 6b: owner "My Devices" (backend slice 6a; owner-only,
    // path-ledger-bound). list / rename / revoke + mint a pairing code to add a
    // device (the new device then pairs via the existing bind flow).
    @GET("api/ledgers/{ledgerId}/devices")
    suspend fun ledgerDevices(@Path("ledgerId") ledgerId: String): MyDeviceListResponseDto

    @POST("api/ledgers/{ledgerId}/devices/{publicId}/rename")
    suspend fun renameLedgerDevice(
        @Path("ledgerId") ledgerId: String,
        @Path("publicId") publicId: String,
        @Body request: DeviceRenameRequestDto,
    ): MyDeviceDto

    @POST("api/ledgers/{ledgerId}/devices/{publicId}/revoke")
    suspend fun revokeLedgerDevice(
        @Path("ledgerId") ledgerId: String,
        @Path("publicId") publicId: String,
    ): MyDeviceDto

    // 204 No Content; Retrofit's built-in Unit converter consumes the empty body.
    @POST("api/ledgers/{ledgerId}/devices/{publicId}/delete")
    suspend fun deleteLedgerDevice(
        @Path("ledgerId") ledgerId: String,
        @Path("publicId") publicId: String,
    )

    @POST("api/ledgers/{ledgerId}/devices/pairing-codes")
    suspend fun createLedgerDevicePairingCode(
        @Path("ledgerId") ledgerId: String,
        @Body request: PairingCodeCreateRequestDto,
    ): PairingCodeResponseDto

    @GET("api/recycle-bin")
    suspend fun recycleBin(): RecycleBinListResponseDto

    @POST("api/recycle-bin/restore")
    suspend fun restoreRecycleBinItem(
        @Body request: RecycleBinRestoreRequestDto,
    ): RecycleBinRestoreResponseDto

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
