package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.CreditDrawViewDto
import com.ticketbox.data.remote.dto.InstallmentPeriodViewDto
import com.ticketbox.data.remote.dto.InstallmentViewDto
import com.ticketbox.data.remote.dto.InstallmentsDto
import com.ticketbox.domain.model.CreditDrawView
import com.ticketbox.domain.model.InstallmentPeriodView
import com.ticketbox.domain.model.InstallmentView
import com.ticketbox.domain.model.Installments

internal fun CreditDrawViewDto.toDomain(): CreditDrawView = CreditDrawView(
    publicId = publicId,
    note = note,
    occurredOn = occurredOn,
    originalMinor = originalMinor,
    remainingMinor = remainingMinor,
    agreementPublicId = agreementPublicId,
)

internal fun InstallmentPeriodViewDto.toDomain(): InstallmentPeriodView = InstallmentPeriodView(
    publicId = publicId,
    position = position,
    dueOn = dueOn,
    principalMinor = principalMinor,
    plannedFeeMinor = plannedFeeMinor,
    paidPrincipalMinor = paidPrincipalMinor,
    paidFeeMinor = paidFeeMinor,
    unincurredFeeMinor = unincurredFeeMinor,
    incurredFeeMinor = incurredFeeMinor,
)

internal fun InstallmentViewDto.toDomain(): InstallmentView = InstallmentView(
    publicId = publicId,
    seriesId = seriesId,
    revision = revision,
    name = name,
    source = source,
    agreedOn = agreedOn,
    active = active,
    needsReview = needsReview,
    remainingPrincipalMinor = remainingPrincipalMinor,
    periods = periods.map { it.toDomain() },
    drawPublicIds = drawPublicIds,
)

internal fun InstallmentsDto.toDomain(): Installments = Installments(
    accountPublicId = accountPublicId,
    accountRowVersion = accountRowVersion,
    currencyCode = currencyCode,
    agreements = agreements.map { it.toDomain() },
    draws = draws.map { it.toDomain() },
)
