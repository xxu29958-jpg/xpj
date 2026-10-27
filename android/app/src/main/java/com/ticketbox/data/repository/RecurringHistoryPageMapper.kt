package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RecurringHistoryPageDto
import com.ticketbox.domain.model.RecurringHistoryPage

internal fun RecurringHistoryPageDto.toDomain() = RecurringHistoryPage(
    ledgerId = ledgerId, publicId = publicId, items = items.map { it.toDomain() },
    nextBeforeVersion = nextBeforeVersion,
)
