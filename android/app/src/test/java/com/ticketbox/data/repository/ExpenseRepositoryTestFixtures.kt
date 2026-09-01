package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto
import com.ticketbox.data.remote.dto.ConfirmedOffsetStreamDto
import com.ticketbox.data.remote.dto.ConfirmedStreamEntryKindDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseFinancialSummaryDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import com.ticketbox.data.remote.dto.ExpenseOffsetResponseDto
import com.ticketbox.data.remote.dto.ExpenseOffsetStatusDto

internal fun cachedConfirmedEntity(
    serverId: Long,
    publicId: String,
    merchant: String,
    ledgerId: String = "owner",
): ExpenseEntity =
    ExpenseEntity(
        ledgerId = ledgerId,
        serverId = serverId,
        publicId = publicId,
        amountCents = 1200,
        merchant = merchant,
        category = "交通",
        note = null,
        source = "缓存",
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "confirmed",
        expenseTime = "2026-05-01T00:00:00Z",
        createdAt = "2026-05-01T00:00:00Z",
        confirmedAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-01T00:00:00Z",
        rowVersion = 1L,
    )

internal fun unsupported(): Nothing = error("Unexpected API call")

internal fun confirmedExpenseDtoFixture(
    id: Long = 9L,
    publicId: String = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
    amountCents: Long = 175_479L,
    merchant: String = "高德",
    category: String = "交通",
    tags: String? = null,
    expenseTime: String = "2026-05-07T07:29:00Z",
    rowVersion: Long = 1L,
): ExpenseDto = ExpenseDto(
    id = id,
    publicId = publicId,
    amountCents = amountCents,
    merchant = merchant,
    category = category,
    note = "",
    source = "Android截图",
    imagePath = null,
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    confidence = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = tags,
    valueScore = null,
    regretScore = null,
    status = "confirmed",
    expenseTime = expenseTime,
    createdAt = "2026-05-09T08:08:13Z",
    updatedAt = "2026-05-09T08:12:40Z",
    rowVersion = rowVersion,
    confirmedAt = "2026-05-09T08:12:40Z",
    rejectedAt = null,
)

internal fun confirmedStreamEnvelopeFixture(
    entryKind: ConfirmedStreamEntryKindDto = ConfirmedStreamEntryKindDto.Expense,
    streamDate: String = "2026-05-07",
    streamSortTime: String = "2026-05-07T07:29:00Z",
    streamSortId: Long = 9,
    streamAmountCents: Long = 175_479L,
    root: ExpenseDto = confirmedExpenseDtoFixture(),
    offset: ConfirmedOffsetStreamDto? = null,
    lineageStatus: ExpenseLineageStatusDto = ExpenseLineageStatusDto.Confirmed,
    lineageHomeNetCents: Long = 175_479L,
): ConfirmedExpenseStreamItemDto = ConfirmedExpenseStreamItemDto(
    entryKind = entryKind,
    streamDate = streamDate,
    streamSortTime = streamSortTime,
    streamSortId = streamSortId,
    streamAmountCents = streamAmountCents,
    root = root,
    offset = offset,
    lineageStatus = lineageStatus,
    lineageHomeNetCents = lineageHomeNetCents,
)

internal fun expenseOffsetResponseDtoFixture(
    publicId: String = "refund-1",
    kind: ExpenseOffsetKindDto = ExpenseOffsetKindDto.Refund,
    originalAmountMinor: Long = 300,
    amountCents: Long = 300,
    streamAmountCents: Long = -300,
    streamSortTime: String = "2026-09-03T04:00:00Z",
    streamSortId: Long = 22,
    accountingDate: String = "2026-09-03",
    rowVersion: Long = 1,
): ExpenseOffsetResponseDto = ExpenseOffsetResponseDto(
    publicId = publicId,
    kind = kind,
    status = ExpenseOffsetStatusDto.Active,
    originalCurrencyCode = "CNY",
    originalAmountMinor = originalAmountMinor,
    homeCurrencyCode = "CNY",
    amountCents = amountCents,
    streamAmountCents = streamAmountCents,
    streamSortTime = streamSortTime,
    streamSortId = streamSortId,
    accountingDate = accountingDate,
    category = "交通",
    reason = "退款到账",
    rowVersion = rowVersion,
    factRevision = 1,
    createdAt = "2026-09-03T04:00:00Z",
    updatedAt = "2026-09-03T04:00:00Z",
)

internal fun expenseFactBundleDtoFixture(
    root: ExpenseDto = confirmedExpenseDtoFixture(amountCents = 1_200, rowVersion = 2),
    status: ExpenseLineageStatusDto = ExpenseLineageStatusDto.PartiallyRefunded,
    rootStreamAmountCents: Long = 1_200,
    lineageHomeNetCents: Long = 900,
    activeOffsets: List<ExpenseOffsetResponseDto> = listOf(expenseOffsetResponseDtoFixture()),
): ExpenseFactBundleDto = ExpenseFactBundleDto(
    root = root,
    financialSummary = ExpenseFinancialSummaryDto(
        grossOriginalMinor = 1_200,
        grossHomeAmountCents = 1_200,
        rootStreamAmountCents = rootStreamAmountCents,
        activeRefundedOriginalMinor = 300,
        remainingRefundableOriginalMinor = 900,
        lineageHomeNetCents = lineageHomeNetCents,
        fxDifferenceCents = 0,
        status = status,
    ),
    activeOffsets = activeOffsets,
)
