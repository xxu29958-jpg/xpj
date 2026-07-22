package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.CategoryPreferenceDto
import com.ticketbox.data.remote.dto.CategoryPreferenceListResponseDto
import com.ticketbox.data.remote.dto.CategoryPreferenceTokenRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.NotificationDraftRequestDto
import com.ticketbox.data.remote.dto.TagsDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.Multipart
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.POST
import retrofit2.http.Query
import retrofit2.http.Streaming

interface ExpenseListApi {
    @GET("api/expenses/pending")
    suspend fun pendingExpenses(): List<ExpenseDto>

    @GET("api/expenses/categories")
    suspend fun categories(): CategoriesDto

    @GET("api/expenses/categories/preferences")
    suspend fun categoryPreferences(): CategoryPreferenceListResponseDto

    @POST("api/expenses/categories/preferences/{publicId}/delete")
    suspend fun deleteCategoryPreference(
        @Path("publicId") publicId: String,
        @Body request: CategoryPreferenceTokenRequestDto,
    ): CategoryPreferenceDto

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

    @GET("api/duplicates")
    suspend fun duplicates(): List<ExpenseDto>
}
