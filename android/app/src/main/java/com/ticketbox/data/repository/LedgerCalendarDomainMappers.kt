package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.domain.model.LedgerCalendar

internal fun LedgerCalendarDto.toDomain(): LedgerCalendar = LedgerCalendar(
    ledgerId = ledgerId,
    revision = revision,
    timezoneName = timezoneName,
    basis = basis,
    adoptedAt = adoptedAt,
)
