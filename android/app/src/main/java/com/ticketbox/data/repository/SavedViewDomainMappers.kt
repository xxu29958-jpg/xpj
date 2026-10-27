package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.SavedViewResultRowDto
import com.ticketbox.data.remote.dto.SavedViewResultsDto
import com.ticketbox.domain.model.SavedViewResultRow
import com.ticketbox.domain.model.SavedViewResults

internal fun SavedViewResultRowDto.toDomain(ledgerId: String): SavedViewResultRow = SavedViewResultRow(
    entry = entry.toDomain(ledgerId),
    projectedAmountCents = projectedAmountCents,
    projectionGap = projectionGap?.toDomain(),
)

internal fun SavedViewResultsDto.toDomain(): SavedViewResults = SavedViewResults(
    conditions = conditions,
    items = items.map { it.toDomain(requireNotNull(conditions["ledger_id"])) },
    page = page,
    pageSize = pageSize,
    total = total,
)

internal fun com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto.toDomain(ledgerId: String): com.ticketbox.domain.model.ConfirmedStreamItem {
    val projection = toConfirmedStreamCacheItem(ledgerId)
    return confirmedStreamFromCache(listOf(projection.root), listOfNotNull(projection.offset)).single()
}
