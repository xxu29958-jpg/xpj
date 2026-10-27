package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RecurringDefinitionDto
import com.ticketbox.data.remote.dto.RecurringRecordedDefinitionDto
import com.ticketbox.data.remote.dto.RecurringRevisionDto
import com.ticketbox.domain.model.RecurringDefinition
import com.ticketbox.domain.model.RecurringRecordedDefinition
import com.ticketbox.domain.model.RecurringRevision

internal fun RecurringDefinitionDto.toDomain(): RecurringDefinition = RecurringDefinition(
    merchant = merchant,
    merchantKey = merchantKey,
    frequency = frequency,
    homeCurrencyCode = homeCurrencyCode,
    baselineAmountCents = baselineAmountCents,
    nextExpectedDate = nextExpectedDate,
    status = status,
    source = source,
)

internal fun RecurringRecordedDefinitionDto.toDomain(): RecurringRecordedDefinition = RecurringRecordedDefinition(
    seriesRowVersion = seriesRowVersion,
    recordedAt = recordedAt,
    snapshot = snapshot.toDomain(),
)

internal fun RecurringRevisionDto.toDomain(): RecurringRevision = RecurringRevision(
    rowVersion = rowVersion,
    changeKind = changeKind,
    recordedAt = recordedAt,
    actorAccountId = actorAccountId,
    snapshot = snapshot.toDomain(),
)
