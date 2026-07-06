package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.TagDeleteRequest
import com.ticketbox.data.remote.dto.TagDetailDto
import com.ticketbox.data.remote.dto.TagManagementListDto
import com.ticketbox.data.remote.dto.TagMergeRequest
import com.ticketbox.data.remote.dto.TagMutationDto
import com.ticketbox.data.remote.dto.TagRenameRequest
import com.ticketbox.data.remote.dto.TagUndoDto
import com.ticketbox.data.remote.dto.TagUndoRequest
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

interface TagApi {
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
}
