package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.InvitationAcceptRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationCreateRequestDto
import com.ticketbox.data.remote.dto.InvitationCreateResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewRequestDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import retrofit2.http.Body
import retrofit2.http.POST
import retrofit2.http.Path

interface InvitationApi {
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
}
