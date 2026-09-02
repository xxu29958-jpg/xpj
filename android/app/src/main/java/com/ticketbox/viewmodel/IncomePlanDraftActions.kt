package com.ticketbox.viewmodel

import com.ticketbox.data.repository.IncomePlanPatch
import com.ticketbox.domain.model.IncomeFrequency

enum class IncomePlanDraftField {
    Label,
    IncomeMonth,
    Amount,
    PayDay,
}

fun IncomePlanViewModel.updateDraftLabel(value: String) =
    updateDraftField(IncomePlanDraftField.Label, value)

fun IncomePlanViewModel.updateDraftIncomeMonth(value: String) =
    updateDraftField(IncomePlanDraftField.IncomeMonth, value)

fun IncomePlanViewModel.updateDraftAmount(value: String) =
    updateDraftField(IncomePlanDraftField.Amount, value)

fun IncomePlanViewModel.updateDraftPayDay(value: String) =
    updateDraftField(IncomePlanDraftField.PayDay, value)

/**
 * 编辑提交的全字段补丁（整表 + OCC token）：MONTHLY 不带 income_month——Moshi 默认不序列化
 * null，后端按 frequency=monthly 归一清掉月份（_updated_income_month 未 provided 时回落现有值再
 * normalize），ONE_TIME 必带解析后的月份。
 */
internal fun IncomePlanDraftUi.toPatchOrNull(expectedRowVersion: Long): IncomePlanPatch? {
    val cleanLabel = label.trim().takeIf(String::isNotEmpty) ?: return null
    val amount = parsedAmountCents() ?: return null
    val payDay = parsedPayDay() ?: return null
    val incomeMonth = when (frequency) {
        IncomeFrequency.MONTHLY -> null
        IncomeFrequency.ONE_TIME -> parsedIncomeMonth() ?: return null
    }
    return IncomePlanPatch(
        expectedRowVersion = expectedRowVersion,
        label = cleanLabel,
        sourceType = sourceType,
        frequency = frequency,
        incomeMonth = incomeMonth,
        amountCents = amount,
        payDay = payDay,
    )
}
