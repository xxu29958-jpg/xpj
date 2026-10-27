package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.MonthlyArrangementDto
import com.ticketbox.data.remote.dto.MonthlyArrangementHistoryDto
import com.ticketbox.data.remote.dto.MonthlyArrangementHistoryItemDto
import com.ticketbox.data.remote.dto.MonthlyArrangementResponseDto
import com.ticketbox.data.remote.dto.MonthlyArrangementSaveRequest
import com.ticketbox.domain.model.MonthlyArrangement
import com.ticketbox.domain.model.MonthlyArrangementChange
import com.ticketbox.domain.model.MonthlyArrangementHistory
import com.ticketbox.domain.model.MonthlyArrangementHistoryItem
import com.ticketbox.domain.model.MonthlyArrangementResponse

internal fun MonthlyArrangementDto.toDomain(): MonthlyArrangement = MonthlyArrangement(
    ledgerId = ledgerId,
    month = month,
    homeCurrencyCode = homeCurrencyCode,
    savingsTargetCents = savingsTargetCents,
    reservedBufferCents = reservedBufferCents,
    rowVersion = rowVersion,
    updatedAt = updatedAt,
)

internal fun MonthlyArrangementHistoryDto.toDomain(): MonthlyArrangementHistory = MonthlyArrangementHistory(
    ledgerId = ledgerId,
    month = month,
    items = items.map { it.toDomain() },
    nextBeforeVersion = nextBeforeVersion,
)

internal fun MonthlyArrangementHistoryItemDto.toDomain(): MonthlyArrangementHistoryItem = MonthlyArrangementHistoryItem(
    rowVersion = rowVersion,
    recordedAt = recordedAt,
    homeCurrencyCode = homeCurrencyCode,
    savingsTargetCents = savingsTargetCents,
    reservedBufferCents = reservedBufferCents,
)

internal fun MonthlyArrangementResponseDto.toDomain(): MonthlyArrangementResponse = MonthlyArrangementResponse(
    ledgerId = ledgerId,
    month = month,
    arrangement = arrangement?.toDomain(),
)

internal fun MonthlyArrangementSaveRequest.toDomain(): MonthlyArrangementChange = MonthlyArrangementChange(
    homeCurrencyCode = homeCurrencyCode,
    savingsTargetCents = savingsTargetCents,
    reservedBufferCents = reservedBufferCents,
    expectedRowVersion = expectedRowVersion,
)

internal fun MonthlyArrangementChange.toDto(): MonthlyArrangementSaveRequest = MonthlyArrangementSaveRequest(
    homeCurrencyCode = homeCurrencyCode,
    savingsTargetCents = savingsTargetCents,
    reservedBufferCents = reservedBufferCents,
    expectedRowVersion = expectedRowVersion,
)

internal fun com.ticketbox.domain.model.MonthlyArrangement.toDto() = MonthlyArrangementDto(
    ledgerId = ledgerId, month = month, homeCurrencyCode = homeCurrencyCode,
    savingsTargetCents = savingsTargetCents, reservedBufferCents = reservedBufferCents,
    rowVersion = rowVersion, updatedAt = updatedAt,
)
