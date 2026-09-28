package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanPatch
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.UiText

enum class IncomePlanDraftField {
    Label,
    IncomeMonth,
    Amount,
    PayDay,
}

fun IncomePlanCreateViewModel.updateDraftLabel(value: String) =
    updateDraftField(IncomePlanDraftField.Label, value)

fun IncomePlanCreateViewModel.updateDraftIncomeMonth(value: String) =
    updateDraftField(IncomePlanDraftField.IncomeMonth, value)

fun IncomePlanCreateViewModel.updateDraftAmount(value: String) =
    updateDraftField(IncomePlanDraftField.Amount, value)

fun IncomePlanCreateViewModel.updateDraftPayDay(value: String) =
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
        intentMonth = intentMonth,
        expectedRowVersion = expectedRowVersion,
        label = cleanLabel,
        sourceType = sourceType,
        frequency = frequency,
        incomeMonth = incomeMonth,
        amountCents = amount,
        payDay = payDay,
    )
}

fun IncomePlanCreateViewModel.updateDraftSource(value: IncomeSourceType) = updateDraftChoice(source = value)
fun IncomePlanCreateViewModel.updateDraftFrequency(value: IncomeFrequency) = updateDraftChoice(frequency = value)

internal fun IncomePlanDraftUi.withAmountValidation(): IncomePlanDraftUi = copy(
    validationError = if (homeCurrency != null && amountYuanInput.isNotBlank() && parsedAmountCents() == null) {
        UiText.res(R.string.expense_edit_amount_invalid)
    } else null,
)

internal fun IncomePlanDraftUi.toRepositoryDraftOrNull(): IncomePlanDraft? {
    if (intentMonth.isEmpty()) return null
    val cleanLabel = label.trim().takeIf(String::isNotEmpty) ?: return null
    val amount = parsedAmountCents() ?: return null
    val payDay = parsedPayDay() ?: return null
    val incomeMonth = when (frequency) {
        IncomeFrequency.MONTHLY -> null
        IncomeFrequency.ONE_TIME -> parsedIncomeMonth() ?: return null
    }
    return IncomePlanDraft(
        intentMonth = intentMonth,
        homeCurrencyCode = homeCurrency?.storageKey ?: return null,
        label = cleanLabel,
        sourceType = sourceType,
        frequency = frequency,
        incomeMonth = incomeMonth,
        amountCents = amount,
        payDay = payDay,
    )
}
