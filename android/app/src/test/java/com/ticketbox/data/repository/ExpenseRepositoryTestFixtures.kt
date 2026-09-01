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

internal data class ConfirmedExpenseFixture(
    val amountCents: Long = 175_479L,
    val merchant: String = "高德",
    val category: String = "交通",
    val tags: String? = null,
    val expenseTime: String = "2026-05-07T07:29:00Z",
    val rowVersion: Long = 1L,
)

internal fun confirmedExpenseDtoFixture(
    fixture: ConfirmedExpenseFixture = ConfirmedExpenseFixture(),
): ExpenseDto = ExpenseDto(
    id = 9L,
    publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
    amountCents = fixture.amountCents,
    merchant = fixture.merchant,
    category = fixture.category,
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
    tags = fixture.tags,
    valueScore = null,
    regretScore = null,
    status = "confirmed",
    expenseTime = fixture.expenseTime,
    createdAt = "2026-05-09T08:08:13Z",
    updatedAt = "2026-05-09T08:12:40Z",
    rowVersion = fixture.rowVersion,
    confirmedAt = "2026-05-09T08:12:40Z",
    rejectedAt = null,
)

internal data class ConfirmedLineageFixture(
    val status: ExpenseLineageStatusDto = ExpenseLineageStatusDto.Confirmed,
    val homeNetCents: Long = 175_479L,
)

internal data class ConfirmedStreamFixture(
    val entryKind: ConfirmedStreamEntryKindDto = ConfirmedStreamEntryKindDto.Expense,
    val streamDate: String = "2026-05-07",
    val streamAmountCents: Long = 175_479L,
    val root: ExpenseDto = confirmedExpenseDtoFixture(),
    val offset: ConfirmedOffsetStreamDto? = null,
    val lineage: ConfirmedLineageFixture = ConfirmedLineageFixture(),
)

internal fun confirmedStreamEnvelopeFixture(
    fixture: ConfirmedStreamFixture = ConfirmedStreamFixture(),
): ConfirmedExpenseStreamItemDto = ConfirmedExpenseStreamItemDto(
    entryKind = fixture.entryKind,
    streamDate = fixture.streamDate,
    streamSortTime = "2026-05-07T07:29:00Z",
    streamSortId = 9,
    streamAmountCents = fixture.streamAmountCents,
    root = fixture.root,
    offset = fixture.offset,
    lineageStatus = fixture.lineage.status,
    lineageHomeNetCents = fixture.lineage.homeNetCents,
)

internal data class ExpenseOffsetFixture(
    val publicId: String = "refund-1",
    val kind: ExpenseOffsetKindDto = ExpenseOffsetKindDto.Refund,
    val amountCents: Long = 300,
    val streamAmountCents: Long = -300,
    val rowVersion: Long = 1,
)

internal fun expenseOffsetResponseDtoFixture(
    fixture: ExpenseOffsetFixture = ExpenseOffsetFixture(),
): ExpenseOffsetResponseDto = ExpenseOffsetResponseDto(
    publicId = fixture.publicId,
    kind = fixture.kind,
    status = ExpenseOffsetStatusDto.Active,
    originalCurrencyCode = "CNY",
    originalAmountMinor = fixture.amountCents,
    homeCurrencyCode = "CNY",
    amountCents = fixture.amountCents,
    streamAmountCents = fixture.streamAmountCents,
    streamSortTime = "2026-09-03T04:00:00Z",
    streamSortId = 22,
    accountingDate = "2026-09-03",
    category = "交通",
    reason = "退款到账",
    rowVersion = fixture.rowVersion,
    factRevision = 1,
    createdAt = "2026-09-03T04:00:00Z",
    updatedAt = "2026-09-03T04:00:00Z",
)

internal fun expenseFactBundleDtoFixture(
    root: ExpenseDto = confirmedExpenseDtoFixture(
        ConfirmedExpenseFixture(amountCents = 1_200, rowVersion = 2),
    ),
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
