package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppFilterChipOptions
import com.ticketbox.ui.components.AppFormFieldGroup
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.IncomePlanDraftUi

/** 表单渲染状态（添加与编辑共用）：草稿 + 提交中 + 账本币种解析中（仅编辑路径会置位）。 */
internal data class IncomePlanDraftFormState(
    val draft: IncomePlanDraftUi,
    val isSubmitting: Boolean,
    val currencyPending: Boolean = false,
)

/** 表单文本/月份步进回调组（添加与编辑共用）；onRetryCurrency 仅编辑路径提供（币种未确认状态行的恢复入口）。 */
internal data class IncomePlanDraftFieldCallbacks(
    val onLabel: (String) -> Unit,
    val onAmount: (String) -> Unit,
    val onPayDay: (String) -> Unit,
    val onPreviousIncomeMonth: () -> Unit,
    val onNextIncomeMonth: () -> Unit,
    val onRetryCurrency: (() -> Unit)? = null,
)

/** 表单选择回调组（来源类型 / 频率）。 */
internal data class IncomePlanDraftChoiceCallbacks(
    val onSourceType: (IncomeSourceType) -> Unit,
    val onFrequency: (IncomeFrequency) -> Unit,
)

/**
 * W2-C 添加/编辑共享的收入表单（纯渲染，VM 持草稿与校验）：金额标签币种用草稿注入的账本
 * capability（VM 已解析）；添加路径未确认时落路由 display 兜底仅作展示（写面由 VM 守门）；
 * 编辑路径未确认时金额位换成「正在准备/未确认可重试」状态行，不留无币种的裸金额输入框。
 */
@Composable
internal fun IncomePlanDraftForm(
    state: IncomePlanDraftFormState,
    currency: CurrencyDisplay,
    fieldCallbacks: IncomePlanDraftFieldCallbacks,
    choiceCallbacks: IncomePlanDraftChoiceCallbacks,
) {
    val draft = state.draft
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.income_plan_sheet_label_name),
            value = draft.label,
            placeholder = stringResource(R.string.income_plan_sheet_name_placeholder),
            enabled = !state.isSubmitting,
        ),
        actions = AppTextInputActions(onValueChange = fieldCallbacks.onLabel),
        modifier = Modifier.fillMaxWidth(),
    )
    IncomePlanDraftChoices(
        draft = draft,
        enabled = !state.isSubmitting,
        fieldCallbacks = fieldCallbacks,
        choiceCallbacks = choiceCallbacks,
    )
    IncomePlanDraftAmountField(
        state = state,
        fallbackCurrency = currency,
        onAmount = fieldCallbacks.onAmount,
        onRetryCurrency = fieldCallbacks.onRetryCurrency,
    )
    IncomePlanDraftPayDayField(
        draft = draft,
        enabled = !state.isSubmitting,
        onPayDay = fieldCallbacks.onPayDay,
    )
    draft.validationError?.let { error ->
        Text(
            error.asString(),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
        )
    }
}

/** 来源类型 / 频率选择 + 一次性月份步进（VM 持草稿，这里纯渲染）。 */
@Composable
private fun IncomePlanDraftChoices(
    draft: IncomePlanDraftUi,
    enabled: Boolean,
    fieldCallbacks: IncomePlanDraftFieldCallbacks,
    choiceCallbacks: IncomePlanDraftChoiceCallbacks,
) {
    IncomePlanDraftChoiceField(
        label = stringResource(R.string.income_plan_sheet_label_type),
        entries = IncomeSourceType.entries.map { it to stringResource(incomeSourceTypeLabelRes(it)) },
        selected = draft.sourceType,
        enabled = enabled,
        onSelect = choiceCallbacks.onSourceType,
    )
    IncomePlanDraftChoiceField(
        label = stringResource(R.string.income_plan_sheet_label_frequency),
        entries = listOf(IncomeFrequency.ONE_TIME, IncomeFrequency.MONTHLY)
            .map { it to stringResource(incomeFrequencyLabelRes(it)) },
        selected = draft.frequency,
        enabled = enabled,
        onSelect = choiceCallbacks.onFrequency,
    )
    if (draft.frequency == IncomeFrequency.ONE_TIME) {
        AppFormFieldGroup(label = stringResource(R.string.income_plan_sheet_label_income_month)) {
            IncomeMonthPicker(
                value = draft.incomeMonthInput,
                onPrevious = fieldCallbacks.onPreviousIncomeMonth,
                onNext = fieldCallbacks.onNextIncomeMonth,
            )
        }
    }
}

@Composable
private fun <T> IncomePlanDraftChoiceField(
    label: String,
    entries: List<Pair<T, String>>,
    selected: T,
    enabled: Boolean,
    onSelect: (T) -> Unit,
) {
    AppFormFieldGroup(label = label) {
        AppCompactChips {
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                entries.forEach { (entry, entryLabel) ->
                    AppFilterChip(
                        selected = selected == entry,
                        onClick = { onSelect(entry) },
                        label = entryLabel,
                        options = AppFilterChipOptions(enabled = enabled),
                    )
                }
            }
        }
    }
}

/**
 * 金额字段：币种已确认 → 正常金额输入（标签币种取草稿注入的 capability，添加路径回落由路由
 * display 兜底仅作展示）；编辑路径且币种未确认 → 状态行（解析中 / 未确认可重试），不渲染无
 * 币种的裸金额输入——R12-D 禁写由 VM 守门，此处给可理解的等待/恢复表达。
 */
@Composable
private fun IncomePlanDraftAmountField(
    state: IncomePlanDraftFormState,
    fallbackCurrency: CurrencyDisplay,
    onAmount: (String) -> Unit,
    onRetryCurrency: (() -> Unit)?,
) {
    val draft = state.draft
    val amountLabel = if (draft.frequency == IncomeFrequency.ONE_TIME) {
        stringResource(R.string.income_plan_sheet_label_amount_one_time)
    } else {
        stringResource(R.string.income_plan_sheet_label_amount_monthly)
    }
    if (onRetryCurrency != null && draft.homeCurrency == null) {
        IncomePlanDraftCurrencyStatusRow(
            label = amountLabel,
            pending = state.currencyPending,
            onRetry = onRetryCurrency,
        )
        return
    }
    AppAmountInput(
        state = AppAmountInputState(
            label = amountLabel,
            currency = draft.homeCurrency ?: fallbackCurrency.homeCurrency,
            value = draft.amountYuanInput,
            placeholder = stringResource(R.string.components_amount_input_placeholder),
            enabled = !state.isSubmitting,
            isError = draft.validationError != null,
        ),
        actions = AppAmountInputActions(onValueChange = onAmount),
    )
}

/** 币种未确认状态行：解析中 → 小型进度 + 「正在准备金额…」；未确认 → 说明 + 重试（其它字段仍可改）。 */
@Composable
private fun IncomePlanDraftCurrencyStatusRow(
    label: String,
    pending: Boolean,
    onRetry: () -> Unit,
) {
    AppFormFieldGroup(label = label) {
        if (pending) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            ) {
                CircularProgressIndicator(
                    modifier = Modifier.size(AppIconSize.standard),
                    strokeWidth = 2.dp,
                )
                Text(
                    stringResource(R.string.income_plan_edit_currency_preparing),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    stringResource(R.string.income_plan_edit_currency_unavailable),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = onRetry) {
                    Text(stringResource(R.string.common_retry))
                }
            }
        }
    }
}

/** 到账/发薪日字段：标签随频率切换。 */
@Composable
private fun IncomePlanDraftPayDayField(
    draft: IncomePlanDraftUi,
    enabled: Boolean,
    onPayDay: (String) -> Unit,
) {
    AppTextInput(
        state = AppTextInputState(
            label = if (draft.frequency == IncomeFrequency.ONE_TIME) {
                stringResource(R.string.income_plan_sheet_label_arrival_day)
            } else {
                stringResource(R.string.income_plan_sheet_label_payday)
            },
            value = draft.payDayInput,
            placeholder = stringResource(R.string.income_plan_sheet_day_placeholder),
            enabled = enabled,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        ),
        actions = AppTextInputActions(onValueChange = onPayDay),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
internal fun IncomeMonthPicker(
    value: String,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        IconButton(onClick = onPrevious) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
                contentDescription = stringResource(R.string.income_plan_month_previous),
            )
        }
        Text(
            text = displayMonthLabel(value),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            textAlign = TextAlign.Center,
            modifier = Modifier.weight(1f),
        )
        IconButton(onClick = onNext) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = stringResource(R.string.income_plan_month_next),
            )
        }
    }
}

@StringRes
internal fun incomeSourceTypeLabelRes(source: IncomeSourceType): Int =
    when (source) {
        IncomeSourceType.SALARY -> R.string.income_plan_source_salary
        IncomeSourceType.BONUS -> R.string.income_plan_source_bonus
        IncomeSourceType.FREELANCE -> R.string.income_plan_source_freelance
        IncomeSourceType.RENTAL -> R.string.income_plan_source_rental
        IncomeSourceType.OTHER -> R.string.income_plan_source_other
    }

@StringRes
internal fun incomeFrequencyLabelRes(frequency: IncomeFrequency): Int =
    when (frequency) {
        IncomeFrequency.MONTHLY -> R.string.income_plan_frequency_monthly
        IncomeFrequency.ONE_TIME -> R.string.income_plan_frequency_one_time
    }
