package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.CategoryPreferenceDto
import com.ticketbox.data.remote.dto.CategoryPreferenceInspectionDto
import com.ticketbox.data.remote.dto.CategoryPreferenceListResponseDto
import com.ticketbox.data.remote.dto.CategoryPreferenceTokenRequestDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

interface CategoryPreferenceApi {
    @GET("api/expenses/categories/preferences")
    suspend fun categoryPreferences(): CategoryPreferenceListResponseDto

    @GET("api/expenses/categories/preferences/{publicId}")
    suspend fun inspectCategoryPreference(@Path("publicId") publicId: String): CategoryPreferenceInspectionDto

    @POST("api/expenses/categories/preferences/{publicId}/delete")
    suspend fun deleteCategoryPreference(
        @Path("publicId") publicId: String,
        @Body request: CategoryPreferenceTokenRequestDto,
    ): CategoryPreferenceDto
}
