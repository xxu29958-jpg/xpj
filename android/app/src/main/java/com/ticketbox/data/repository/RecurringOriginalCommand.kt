package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import com.ticketbox.domain.model.CurrencyCode

internal const val RECURRING_ORIGINAL_UNSUPPORTED = "这份原提交的币种或版本依据不完整，请先核对记录。原提交仍保留。"
internal const val RECURRING_RECEIPT_UNVERIFIED = "尚未确认这份固定支出提交已被接受，请先核对记录。原提交仍保留。"
internal const val RECURRING_CONNECTION_INTERRUPTED = "连接中断，保留原固定支出提交等待重试。"

internal fun RecurringItemCreateRequestDto.matchesOriginal(row: OutboxRow): Boolean =
    !row.idempotencyKey.isNullOrBlank() && row.targetId == "recurring_item_create:${row.idempotencyKey}" &&
        row.expectedRowVersion == 0L && CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode) != null &&
        merchant.isNotBlank() && baselineAmountCents > 0

internal fun RecurringItemUpdateRequestDto.matchesOriginal(row: OutboxRow): Boolean =
    !row.idempotencyKey.isNullOrBlank() && row.targetId.startsWith("recurring_item:") &&
        row.targetId.removePrefix("recurring_item:").isNotBlank() &&
        expectedRowVersion > 0 && expectedRowVersion == row.expectedRowVersion &&
        CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode) != null &&
        (merchant == null || merchant.isNotBlank()) && (baselineAmountCents == null || baselineAmountCents > 0)

internal fun RecurringItemDto.confirms(row: OutboxRow, request: RecurringItemCreateRequestDto): Boolean =
    publicId.isNotBlank() && ledgerId == row.ledgerId && homeCurrencyCode == request.homeCurrencyCode &&
        rowVersion == 1L && merchant == request.merchant && baselineAmountCents == request.baselineAmountCents &&
        lastAmountCents == request.baselineAmountCents && nextExpectedDate == request.nextExpectedDate &&
        source == "manual" && status == "active" && frequency == "monthly" && occurrenceCount == 0 && lastSeenAt == null

internal fun RecurringItemDto.confirms(row: OutboxRow, request: RecurringItemUpdateRequestDto): Boolean =
    publicId == row.targetId.removePrefix("recurring_item:") && ledgerId == row.ledgerId &&
        homeCurrencyCode == request.homeCurrencyCode && rowVersion == request.expectedRowVersion + 1 &&
        (request.merchant == null || merchant == request.merchant) &&
        (request.baselineAmountCents == null || baselineAmountCents == request.baselineAmountCents) &&
        (!request.nextExpectedDate.changed || nextExpectedDate == request.nextExpectedDate.value)
