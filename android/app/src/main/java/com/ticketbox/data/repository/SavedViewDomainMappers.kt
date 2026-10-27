package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.SavedViewDefinitionRequestDto
import com.ticketbox.data.remote.dto.SavedViewDeletionReceiptDto
import com.ticketbox.data.remote.dto.SavedViewDto
import com.ticketbox.data.remote.dto.SavedViewResultRowDto
import com.ticketbox.data.remote.dto.SavedViewResultsDto
import com.ticketbox.domain.model.SavedView
import com.ticketbox.domain.model.SavedViewDefinitionRequest
import com.ticketbox.domain.model.SavedViewDeletionReceipt
import com.ticketbox.domain.model.SavedViewResultRow
import com.ticketbox.domain.model.SavedViewResults

internal fun SavedViewDefinitionRequestDto.toDomain(): SavedViewDefinitionRequest = SavedViewDefinitionRequest(
    name = name,
    monthMode = monthMode,
    month = month,
    filter = filter,
    tagPublicId = tagPublicId,
    homeCurrencyCode = homeCurrencyCode,
    queryText = queryText,
    category = category,
)

internal fun SavedViewDefinitionRequest.toDto(): SavedViewDefinitionRequestDto = SavedViewDefinitionRequestDto(
    name = name,
    monthMode = monthMode,
    month = month,
    filter = filter,
    tagPublicId = tagPublicId,
    homeCurrencyCode = homeCurrencyCode,
    queryText = queryText,
    category = category,
)

internal fun SavedViewDeletionReceiptDto.toDomain(): SavedViewDeletionReceipt = SavedViewDeletionReceipt(
    publicId = publicId,
    rowVersion = rowVersion,
    name = name,
)

internal fun SavedViewDeletionReceipt.toDto(): SavedViewDeletionReceiptDto = SavedViewDeletionReceiptDto(
    publicId = publicId,
    rowVersion = rowVersion,
    name = name,
)

internal fun SavedViewDto.toDomain(): SavedView = SavedView(
    publicId = publicId,
    name = name,
    rowVersion = rowVersion,
    monthMode = monthMode,
    month = month,
    filter = filter,
    tagPublicId = tagPublicId,
    tagName = tagName,
    homeCurrencyCode = homeCurrencyCode,
    repairReason = repairReason,
    queryText = queryText,
    category = category,
)

internal fun SavedView.toDto(): SavedViewDto = SavedViewDto(
    publicId = publicId,
    name = name,
    rowVersion = rowVersion,
    monthMode = monthMode,
    month = month,
    filter = filter,
    tagPublicId = tagPublicId,
    tagName = tagName,
    homeCurrencyCode = homeCurrencyCode,
    repairReason = repairReason,
    queryText = queryText,
    category = category,
)

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
