package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.InvitationCreateResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.InvitationSummaryDto
import com.ticketbox.domain.model.FamilyInvitation
import com.ticketbox.domain.model.FamilyInvitationCreated
import com.ticketbox.domain.model.InvitationPreview

internal fun InvitationPreviewResponseDto.toInvitationPreview(): InvitationPreview = InvitationPreview(
    serverId = serverId.requireSessionProtocolId("服务器身份"),
    dataGeneration = dataGeneration.requireSessionProtocolId("数据代际"),
    ledgerId = ledgerId,
    ledgerName = ledgerName,
    role = role,
    expiresAt = expiresAt,
)

internal fun InvitationCreateResponseDto.toFamilyInvitationCreated(): FamilyInvitationCreated =
    FamilyInvitationCreated(
        inviteToken = inviteToken,
        inviteUrl = inviteUrl,
        role = invitation.role,
        expiresAt = invitation.expiresAt,
        publicId = invitation.publicId,
    )

internal fun InvitationSummaryDto.toFamilyInvitation() = FamilyInvitation(
    publicId, ledgerId, role, note, createdAt, expiresAt, usedAt, revokedAt, usedByAccountName,
)
