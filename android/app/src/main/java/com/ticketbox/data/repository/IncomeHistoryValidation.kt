package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.IncomeDefinitionDto
import com.ticketbox.data.remote.dto.IncomeHistoryResponseDto
import com.ticketbox.data.remote.dto.IncomeRevisionDto
import com.ticketbox.domain.model.CurrencyCode
import java.time.Instant
import java.time.YearMonth

internal fun IncomeHistoryResponseDto.validateIncomeHistory(binding: LogicalSessionBinding, id: String, before: Long?) {
    require(ledgerId == binding.ledgerId && publicId == id && items.size <= 20) { "收入历史身份无法核对。" }
    require(items.zipWithNext().all { (newer, older) -> newer.rowVersion > older.rowVersion }) { "收入历史顺序无法核对。" }
    require(nextBeforeVersion == null || (items.isNotEmpty() && nextBeforeVersion == items.last().rowVersion)) { "收入历史分页无法核对。" }
    items.forEach { it.validateRevision(before) }
}

private fun IncomeRevisionDto.validateRevision(before: Long?) {
    require(rowVersion > 0 && (before == null || rowVersion < before)) { "收入历史版本无法核对。" }
    require(changeKind in setOf("baseline", "create", "edit", "archive", "restore")) { "收入历史类型暂不支持。" }
    Instant.parse(recordedAt)
    val monthsKnown = intentMonth != null && effectiveMonth != null
    val monthsUnknown = intentMonth == null && effectiveMonth == null
    require(if (changeKind == "baseline") monthsUnknown else monthsKnown) { "收入历史月份无法核对。" }
    intentMonth?.let(YearMonth::parse)
    effectiveMonth?.let(YearMonth::parse)
    snapshot.validateDefinition()
}

private fun IncomeDefinitionDto.validateDefinition() {
    require(amountCents >= 0 && payDay in 1..31 && status in setOf("active", "archived")) { "原收入计划无法核对。" }
    require(homeCurrencyCode == null || CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode) != null) { "原收入币种暂不支持。" }
    require(frequency in setOf("monthly", "one_time") &&
        (incomeMonth != null) == (frequency == "one_time")) { "原收入预计月份无法核对。" }
    incomeMonth?.let(YearMonth::parse)
}
