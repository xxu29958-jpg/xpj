package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.IncomeDefinitionDto
import com.ticketbox.data.remote.dto.IncomePlanListResponseDto
import com.ticketbox.domain.model.CurrencyCode
import java.time.Instant
import java.time.YearMonth

internal fun IncomePlanListResponseDto.validateIncomeListing(status: String) {
    require(status in setOf("active", "archived")) { "收入列表范围不正确。" }
    YearMonth.parse(month)
    require(effectivePlanCount >= 0 && items.map { it.publicId }.distinct().size == items.size) { "收入列表无法核对。" }
    require(homeCurrencyCode == null || CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode) != null) { "收入预测币种暂不支持。" }
    require(listOf(totalActiveAmountCents, expectedAmountCents, scheduledAmountCents).all { it == null || it >= 0 }) { "收入预测金额无法核对。" }
    items.forEach { plan ->
        require(plan.publicId.isNotBlank() && plan.rowVersion > 0 && plan.status == status) { "收入计划身份无法核对。" }
        IncomeDefinitionDto(plan.label, plan.sourceType, plan.frequency, plan.incomeMonth,
            plan.amountCents, plan.homeCurrencyCode, plan.payDay, plan.status).validateIncomeDefinition()
        Instant.parse(plan.createdAt)
        Instant.parse(plan.updatedAt)
        plan.archivedAt?.let(Instant::parse)
    }
}
