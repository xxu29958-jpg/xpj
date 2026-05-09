package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.PairRequestDto
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
}
