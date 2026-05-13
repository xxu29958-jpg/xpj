package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
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
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.OwnerTransferResponseDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.PairRequestDto
import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringCandidatesResponseDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.DataQualitySummaryDto
import com.ticketbox.data.remote.dto.PairResponseDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.data.remote.dto.StatusDto
import com.ticketbox.data.remote.dto.UploadResponseDto
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
import retrofit2.http.Query
import retrofit2.http.Streaming

interface ApiService {
    @GET("api/auth/check")
    suspend fun checkAuth(): AuthCheckDto

    @POST("api/auth/pair")
    suspend fun pairDevice(@Body request: PairRequestDto): PairResponseDto

    @GET("api/expenses/pending")
    suspend fun pendingExpenses(): List<ExpenseDto>

    @GET("api/expenses/confirmed")
    suspend fun confirmedExpenses(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 50,
        @Query("month") month: String? = null,
        @Query("category") category: String? = null,
        @Query("timezone") timezone: String? = null,
    ): PaginatedExpensesDto

    @GET("api/expenses/categories")
    suspend fun categories(): CategoriesDto

    @GET("api/expenses/months")
    suspend fun months(@Query("timezone") timezone: String? = null): MonthsDto

    @GET("api/expenses/export.csv")
    @Streaming
    suspend fun exportCsv(
        @Query("month") month: String? = null,
        @Query("category") category: String? = null,
        @Query("timezone") timezone: String? = null,
    ): Response<ResponseBody>

    @POST("api/expenses/manual")
    suspend fun createManualExpense(@Body request: ExpenseUpdateRequest): ExpenseDto

    @Multipart
    @POST("api/app/upload-screenshot")
    suspend fun uploadScreenshot(
        @Part file: MultipartBody.Part,
        @Header("X-Timezone") timezone: String? = null,
    ): UploadResponseDto

    @PATCH("api/expenses/{id}")
    suspend fun updateExpense(
        @Path("id") id: Long,
        @Body request: ExpenseUpdateRequest,
    ): ExpenseDto

    @POST("api/expenses/{id}/confirm")
    suspend fun confirmExpense(@Path("id") id: Long): ExpenseDto

    @POST("api/expenses/{id}/reject")
    suspend fun rejectExpense(@Path("id") id: Long): ExpenseDto

    @POST("api/expenses/{id}/ocr/retry")
    suspend fun retryOcr(@Path("id") id: Long): ExpenseDto

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

    @GET("api/settings/server")
    suspend fun serverSettings(): ServerSettingsDto

    @GET("api/stats/monthly")
    suspend fun monthlyStats(
        @Query("month") month: String? = null,
        @Query("timezone") timezone: String? = null,
    ): MonthlyStatsDto

    @GET("api/stats/lifestyle")
    suspend fun lifestyleStats(
        @Query("month") month: String? = null,
        @Query("timezone") timezone: String? = null,
    ): LifestyleStatsDto

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
}
