package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.local.ExpenseOffsetStreamEntity
import com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto
import com.ticketbox.data.remote.dto.ConfirmedStreamEntryKindDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.StreamOffset
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException

internal data class ConfirmedStreamCacheItem(
    val root: ExpenseEntity,
    val offset: ExpenseOffsetStreamEntity?,
)

internal fun ConfirmedExpenseStreamItemDto.toConfirmedStreamCacheItem(
    ledgerId: String,
): ConfirmedStreamCacheItem {
    val isOffset = when (entryKind) {
        ConfirmedStreamEntryKindDto.Expense -> false
        ConfirmedStreamEntryKindDto.Offset -> true
    }
    if (isOffset != (offset != null)) {
        throw streamContractError("流水类型与退款事实不匹配")
    }
    if (root.status != "confirmed") {
        throw streamContractError("流水原账单不是已确认事实")
    }
    requireConfirmedStreamDate(streamDate)
    confirmedStreamSortInstant(streamSortTime)

    val rootEntity = root.toEntity(ledgerId).copy(
        streamDate = if (isOffset) null else streamDate,
        streamSortTime = if (isOffset) null else streamSortTime,
        streamSortId = if (isOffset) null else streamSortId,
        streamAmountCents = if (isOffset) null else streamAmountCents,
        lineageStatus = lineageStatus.wireValue,
        lineageHomeNetCents = lineageHomeNetCents,
    )
    val offsetEntity = offset?.let { projection ->
        ExpenseOffsetStreamEntity(
            ledgerId = ledgerId,
            publicId = projection.publicId,
            rootServerId = root.id,
            kind = projection.kind.wireValue,
            streamDate = streamDate,
            streamSortTime = streamSortTime,
            streamSortId = streamSortId,
            streamAmountCents = streamAmountCents,
            amountCents = projection.amountCents,
            originalAmountMinor = projection.originalAmountMinor,
            originalCurrencyCode = projection.originalCurrencyCode,
            homeCurrencyCode = projection.homeCurrencyCode,
            category = projection.category,
        )
    }
    return ConfirmedStreamCacheItem(root = rootEntity, offset = offsetEntity)
}

internal fun confirmedStreamFromCache(
    roots: List<ExpenseEntity>,
    offsets: List<ExpenseOffsetStreamEntity>,
): List<ConfirmedStreamItem> {
    val rootsByServerId = roots.mapNotNull { root -> root.serverId?.let { it to root } }.toMap()
    val rootRows = roots.mapNotNull { root ->
        val date = root.streamDate ?: return@mapNotNull null
        val sortTime = root.streamSortTime ?: return@mapNotNull null
        val sortId = root.streamSortId ?: return@mapNotNull null
        val amount = root.streamAmountCents ?: return@mapNotNull null
        val lineage = root.lineage()
        val net = root.lineageHomeNetCents ?: throw streamContractError("原账单缺少净额")
        CachedConfirmedStreamRow(
            item = ConfirmedStreamItem.ExpenseRow(date, amount, root.toDomain(), lineage, net),
            sortTime = confirmedStreamSortInstant(sortTime),
            sortId = sortId,
            entryKind = ConfirmedStreamEntryKindDto.Expense,
        )
    }
    val offsetRows = offsets.map { offset ->
        val root = rootsByServerId[offset.rootServerId]
            ?: throw streamContractError("退款事实找不到原账单")
        val kind = ExpenseOffsetKindDto.fromWire(offset.kind)?.toDomain()
            ?: throw streamContractError("无法识别的退款事实类型")
        CachedConfirmedStreamRow(
            item = ConfirmedStreamItem.OffsetRow(
                streamDate = offset.streamDate,
                streamAmountCents = offset.streamAmountCents,
                root = root.toDomain(),
                lineageStatus = root.lineage(),
                lineageHomeNetCents = root.lineageHomeNetCents
                    ?: throw streamContractError("原账单缺少净额"),
                offset = StreamOffset(
                    publicId = offset.publicId,
                    kind = kind,
                    amountCents = offset.amountCents,
                    originalAmountMinor = offset.originalAmountMinor,
                    originalCurrencyCode = offset.originalCurrencyCode,
                    homeCurrencyCode = offset.homeCurrencyCode,
                    category = offset.category,
                ),
            ),
            sortTime = confirmedStreamSortInstant(offset.streamSortTime),
            sortId = offset.streamSortId,
            entryKind = ConfirmedStreamEntryKindDto.Offset,
        )
    }
    return (rootRows + offsetRows).sortedWith(
        compareByDescending<CachedConfirmedStreamRow> { it.item.streamDate }
            .thenByDescending { it.sortTime }
            .thenByDescending { it.sortId }
            .thenByDescending { it.entryKind.wireValue },
    ).map { it.item }
}

private data class CachedConfirmedStreamRow(
    val item: ConfirmedStreamItem,
    val sortTime: Instant,
    val sortId: Long,
    val entryKind: ConfirmedStreamEntryKindDto,
)

internal fun requireConfirmedStreamDate(value: String): String = try {
    LocalDate.parse(value)
    value
} catch (_: DateTimeParseException) {
    throw streamContractError("流水入账日期无效")
}

internal fun confirmedStreamSortInstant(value: String): Instant = try {
    OffsetDateTime.parse(value).toInstant()
} catch (_: DateTimeParseException) {
    throw streamContractError("流水排序时间无效")
}

private fun ExpenseEntity.lineage() = ExpenseLineageStatusDto.fromWire(lineageStatus)?.toDomain()
    ?: throw streamContractError("无法识别的账单净额状态")

private fun streamContractError(message: String) = RepositoryException(
    message = "账本流水暂时无法读取：$message，请升级应用或稍后重试。",
    errorCode = "confirmed_stream_contract_mismatch",
)
