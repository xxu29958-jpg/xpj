package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.local.ExpenseOffsetStreamEntity
import com.ticketbox.data.remote.dto.AcceptedInvitationImpactDto
import com.ticketbox.data.remote.dto.CancelledPendingInvitationImpactDto
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.ExpenseOffsetChangeKindDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import com.ticketbox.data.remote.dto.ExpenseOffsetResponseDto
import com.ticketbox.data.remote.dto.ExpenseOffsetRevisionDto
import com.ticketbox.data.remote.dto.ExpenseOffsetStatusDto
import com.ticketbox.data.remote.dto.ExpenseRelationshipReasonDto
import com.ticketbox.domain.model.AcceptedInvitationImpact
import com.ticketbox.domain.model.CancelledPendingInvitationImpact
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseFinancialSummary
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.ExpenseOffsetChangeKind
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.ExpenseOffsetRevision
import com.ticketbox.domain.model.ExpenseOffsetStatus
import com.ticketbox.domain.model.ExpenseRelationshipImpacts
import com.ticketbox.domain.model.ExpenseRelationshipReason
import com.ticketbox.domain.model.StreamOffsetKind

internal data class ExpenseFactCacheProjection(
    val root: ExpenseEntity,
    val activeOffsets: List<ExpenseOffsetStreamEntity>,
)

internal fun ExpenseFactBundleDto.toDomain(): ExpenseFactBundle = ExpenseFactBundle(
    root = root.toDomain(),
    financialSummary = ExpenseFinancialSummary(
        grossOriginalMinor = financialSummary.grossOriginalMinor,
        grossHomeAmountCents = financialSummary.grossHomeAmountCents,
        rootStreamAmountCents = financialSummary.rootStreamAmountCents,
        activeRefundedOriginalMinor = financialSummary.activeRefundedOriginalMinor,
        remainingRefundableOriginalMinor = financialSummary.remainingRefundableOriginalMinor,
        lineageHomeNetCents = financialSummary.lineageHomeNetCents,
        fxDifferenceCents = financialSummary.fxDifferenceCents,
        status = financialSummary.status.toDomain(),
    ),
    activeOffsets = activeOffsets.map(ExpenseOffsetResponseDto::toDomain),
    recentHistory = recentHistory.map(ExpenseOffsetRevisionDto::toDomain),
    relationshipImpacts = ExpenseRelationshipImpacts(
        pendingInvitesCancelled = relationshipImpacts.pendingInvitesCancelled.map(
            CancelledPendingInvitationImpactDto::toDomain,
        ),
        acceptedImpacts = relationshipImpacts.acceptedImpacts.map(AcceptedInvitationImpactDto::toDomain),
    ),
)

internal fun ExpenseFactBundleDto.toCacheProjection(ledgerId: String): ExpenseFactCacheProjection {
    val rootId = root.id
    val rootProjection = root.toEntity(ledgerId).copy(
        streamAmountCents = financialSummary.rootStreamAmountCents,
        lineageStatus = financialSummary.status.wireValue,
        lineageHomeNetCents = financialSummary.lineageHomeNetCents,
    )
    val offsets = activeOffsets.map { offset ->
        if (offset.status != ExpenseOffsetStatusDto.Active) {
            throw RepositoryException(
                message = "账单退款事实暂时无法读取，请稍后重试。",
                errorCode = "expense_offset_contract_mismatch",
            )
        }
        ExpenseOffsetStreamEntity(
            ledgerId = ledgerId,
            publicId = offset.publicId,
            rootServerId = rootId,
            kind = offset.kind.wireValue,
            streamDate = requireConfirmedStreamDate(offset.accountingDate),
            streamSortTime = offset.streamSortTime.also { confirmedStreamSortInstant(it) },
            streamSortId = offset.streamSortId,
            streamAmountCents = offset.streamAmountCents,
            amountCents = offset.amountCents,
            originalAmountMinor = offset.originalAmountMinor,
            originalCurrencyCode = offset.originalCurrencyCode,
            homeCurrencyCode = offset.homeCurrencyCode,
            category = offset.category,
        )
    }
    return ExpenseFactCacheProjection(rootProjection, offsets)
}

internal fun ExpenseLineageStatusDto.toDomain(): ExpenseLineageStatus = when (this) {
    ExpenseLineageStatusDto.Confirmed -> ExpenseLineageStatus.Confirmed
    ExpenseLineageStatusDto.PartiallyRefunded -> ExpenseLineageStatus.PartiallyRefunded
    ExpenseLineageStatusDto.FullyRefunded -> ExpenseLineageStatus.FullyRefunded
    ExpenseLineageStatusDto.Reversed -> ExpenseLineageStatus.Reversed
}

internal fun ExpenseOffsetKindDto.toDomain(): StreamOffsetKind = when (this) {
    ExpenseOffsetKindDto.Refund -> StreamOffsetKind.Refund
    ExpenseOffsetKindDto.Chargeback -> StreamOffsetKind.Chargeback
    ExpenseOffsetKindDto.Reversal -> StreamOffsetKind.Reversal
}

internal fun StreamOffsetKind.toDto(): ExpenseOffsetKindDto = when (this) {
    StreamOffsetKind.Refund -> ExpenseOffsetKindDto.Refund
    StreamOffsetKind.Chargeback -> ExpenseOffsetKindDto.Chargeback
    StreamOffsetKind.Reversal -> ExpenseOffsetKindDto.Reversal
}

private fun ExpenseOffsetResponseDto.toDomain(): ExpenseOffsetFact = ExpenseOffsetFact(
    publicId = publicId,
    kind = kind.toDomain(),
    status = when (status) {
        ExpenseOffsetStatusDto.Active -> ExpenseOffsetStatus.Active
        ExpenseOffsetStatusDto.Voided -> ExpenseOffsetStatus.Voided
    },
    originalCurrencyCode = originalCurrencyCode,
    originalAmountMinor = originalAmountMinor,
    homeCurrencyCode = homeCurrencyCode,
    amountCents = amountCents,
    streamAmountCents = streamAmountCents,
    accountingDate = accountingDate,
    category = category,
    reason = reason,
    rowVersion = rowVersion,
    factRevision = factRevision,
    createdAt = createdAt,
    updatedAt = updatedAt,
)

private fun ExpenseOffsetRevisionDto.toDomain(): ExpenseOffsetRevision = ExpenseOffsetRevision(
    publicId = publicId,
    offsetPublicId = offsetPublicId,
    revisionNumber = revisionNumber,
    changeKind = changeKind.toDomain(),
    reason = reason,
    actorAccountName = actorAccountName,
    actorDeviceName = actorDeviceName,
    createdAt = createdAt,
)

private fun CancelledPendingInvitationImpactDto.toDomain() = CancelledPendingInvitationImpact(
    invitationPublicId = invitationPublicId,
    reason = cancellationReasonCode.toDomain(),
)

private fun AcceptedInvitationImpactDto.toDomain() = AcceptedInvitationImpact(
    invitationPublicId = invitationPublicId,
    reason = sourceReasonCode.toDomain(),
    receiverDisplayName = receiverDisplayName,
    debtPublicId = debtPublicId,
    originalAgreedShareHomeMinor = originalAgreedShareHomeMinor,
    suggestedNetShareHomeMinor = suggestedNetShareHomeMinor,
)

private fun ExpenseRelationshipReasonDto.toDomain(): ExpenseRelationshipReason = when (this) {
    ExpenseRelationshipReasonDto.SourceRefunded -> ExpenseRelationshipReason.SourceRefunded
    ExpenseRelationshipReasonDto.SourceChargeback -> ExpenseRelationshipReason.SourceChargeback
    ExpenseRelationshipReasonDto.SourceReversed -> ExpenseRelationshipReason.SourceReversed
}

private fun ExpenseOffsetChangeKindDto.toDomain(): ExpenseOffsetChangeKind = when (this) {
    ExpenseOffsetChangeKindDto.Created -> ExpenseOffsetChangeKind.Created
    ExpenseOffsetChangeKindDto.Correction -> ExpenseOffsetChangeKind.Correction
    ExpenseOffsetChangeKindDto.Void -> ExpenseOffsetChangeKind.Void
}
