package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.EnvelopeAccountDto
import com.ticketbox.data.remote.dto.EnvelopeMonthDto
import com.ticketbox.data.remote.dto.EnvelopePurposeDto
import com.ticketbox.data.remote.dto.EnvelopeRevisionDto
import com.ticketbox.data.remote.dto.EnvelopeSnapshotDto
import com.ticketbox.data.remote.dto.EnvelopesDto
import com.ticketbox.domain.model.EnvelopeAccount
import com.ticketbox.domain.model.EnvelopeMonth
import com.ticketbox.domain.model.EnvelopePurpose
import com.ticketbox.domain.model.EnvelopeRevision
import com.ticketbox.domain.model.EnvelopeSnapshot
import com.ticketbox.domain.model.Envelopes

internal fun EnvelopeAccountDto.toDomain(): EnvelopeAccount = EnvelopeAccount(
    name = name,
    publicId = publicId,
    currencyCode = currencyCode,
    balanceMinor = balanceMinor,
    rowVersion = rowVersion,
    selected = selected,
    canSelect = canSelect,
)

internal fun EnvelopeMonthDto.toDomain(): EnvelopeMonth = EnvelopeMonth(
    month = month,
    reservedMinor = reservedMinor,
)

internal fun EnvelopePurposeDto.toDomain(): EnvelopePurpose = EnvelopePurpose(
    purpose = purpose,
    label = label,
    funded = funded,
    plannedMinor = plannedMinor,
    allocatedMinor = allocatedMinor,
    spentMinor = spentMinor,
    unpaidCreditMinor = unpaidCreditMinor,
    unlinkedMinor = unlinkedMinor,
    availableMinor = availableMinor,
    reservedMinor = reservedMinor,
)

internal fun EnvelopeRevisionDto.toDomain(): EnvelopeRevision = EnvelopeRevision(
    rowVersion = rowVersion,
    month = month,
    reason = reason,
    recordedAt = recordedAt,
    allocationSnapshot = allocationSnapshot.toDomain(),
)

internal fun EnvelopeSnapshotDto.toDomain(): EnvelopeSnapshot = EnvelopeSnapshot(
    homeCurrencyCode = homeCurrencyCode,
    accountPublicIds = accountPublicIds,
    allocations = allocations,
)

internal fun EnvelopesDto.toDomain(): Envelopes = Envelopes(
    ledgerId = ledgerId,
    month = month,
    homeCurrencyCode = homeCurrencyCode,
    rowVersion = rowVersion,
    readAt = readAt,
    valuationDate = valuationDate,
    cashMinor = cashMinor,
    reservedMinor = reservedMinor,
    unassignedMinor = unassignedMinor,
    accounts = accounts.map { it.toDomain() },
    purposes = purposes.map { it.toDomain() },
    months = months.map { it.toDomain() },
    notices = notices,
)
