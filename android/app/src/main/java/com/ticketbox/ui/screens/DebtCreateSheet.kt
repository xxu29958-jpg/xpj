package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SheetState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.DebtDraftUi
import com.ticketbox.viewmodel.DebtListUiState
import com.ticketbox.viewmodel.DebtListViewModel
import com.ticketbox.viewmodel.updateDraftAmount
import com.ticketbox.viewmodel.updateDraftCounterparty
import com.ticketbox.viewmodel.updateDraftDirection
import com.ticketbox.viewmodel.updateDraftInstallmentCount
import com.ticketbox.viewmodel.updateDraftInstallmentPeriod
import com.ticketbox.viewmodel.updateDraftKind
import com.ticketbox.viewmodel.updateDraftNote

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun DebtAddSheet(
    state: DebtListUiState,
    viewModel: DebtListViewModel,
    sheetState: SheetState,
    onClose: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onClose, sheetState = sheetState) {
        DebtDraftForm(
            state = state,
            viewModel = viewModel,
            onSubmit = { viewModel.submitDraft() },
            onCancel = onClose,
        )
    }
}

@Composable
private fun DebtDraftForm(
    state: DebtListUiState,
    viewModel: DebtListViewModel,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    val draft = state.addDraft
    AppSheetScaffold(title = stringResource(R.string.debt_create_sheet_title)) {
        DebtDirectionField(selected = draft.direction, onSelect = viewModel::updateDraftDirection)
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.debt_create_label_counterparty),
                value = draft.counterpartyLabel,
            ),
            actions = AppTextInputActions(onValueChange = viewModel::updateDraftCounterparty),
            modifier = Modifier.fillMaxWidth(),
        )
        AppAmountInput(
            state = AppAmountInputState(
                label = stringResource(R.string.debt_create_label_amount),
                // 显示与解析同源于草稿币种（VM 由账本欠款回填/重绑），不读恒 Base 的
                // 路由级 display（PR#255 P1-3）。
                currency = draft.homeCurrency,
                value = draft.amountYuanInput,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                isError = draft.validationError != null,
            ),
            actions = AppAmountInputActions(onValueChange = viewModel::updateDraftAmount),
            modifier = Modifier.fillMaxWidth(),
        )
        DebtKindCreateField(selected = draft.kind, onSelect = viewModel::updateDraftKind)
        DebtContextField(draft = draft, enabled = !state.isSubmitting, onValueChange = viewModel::updateDraftNote)
        DebtInstallmentCountField(kind = draft.kind, countInput = draft.installmentCountInput, onValueChange = viewModel::updateDraftInstallmentCount)
        DebtInstallmentPeriodField(kind = draft.kind, periodInput = draft.installmentPeriodInput, onValueChange = viewModel::updateDraftInstallmentPeriod)
        draft.validationError?.let { err ->
            AppStatusBanner(message = err, tone = MessageTone.Danger)
        }
        // 空账本 fail closed（PR#255 R4 P1）：列表加载完成但币种仍无 record 级权威依据
        // （空账本）时，说明创建为何禁用 —— 兜底 CNY 口径提交会放大零小数账本 100×。
        // R1 用户可见重试：加载失败同样走到这里，refresh 重试保留草稿、不碰提交门。
        if (!state.homeCurrencyResolved && !state.isLoading) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                AppStatusBanner(
                    message = UiText.res(R.string.debt_create_currency_unconfirmed),
                    tone = MessageTone.Info,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = viewModel::refresh, enabled = !state.isSubmitting) {
                    Text(stringResource(R.string.common_retry))
                }
            }
        }
        AppSheetActionRow(
            primary = AppSheetAction(
                text = if (state.isSubmitting) {
                    stringResource(R.string.debt_create_submitting)
                } else {
                    stringResource(R.string.debt_create_save)
                },
                onClick = onSubmit,
                // 账本币种未确认（初始/切换加载未成功）禁用创建：兜底 CNY 口径提交到
                // JPY/KRW 账本会放大 100×（PR#255 P1-3，VM submitDraft 另有同条件防线）。
                enabled = !state.isSubmitting && state.homeCurrencyResolved,
            ),
            secondary = AppSheetAction(
                text = stringResource(R.string.common_cancel),
                onClick = onCancel,
                enabled = !state.isSubmitting,
            ),
        )
    }
}

@Composable
private fun DebtContextField(draft: DebtDraftUi, enabled: Boolean, onValueChange: (String) -> Unit) {
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.debt_create_label_note),
            value = draft.note,
            placeholder = stringResource(R.string.debt_context_hint),
            trailingLabel = "${draft.noteCharacterCount}/500",
            singleLine = false,
            minLines = 2,
            isError = draft.noteTooLong,
            enabled = enabled,
        ),
        actions = AppTextInputActions(onValueChange = onValueChange),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun DebtDirectionField(selected: String, onSelect: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            stringResource(R.string.debt_create_label_direction),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            listOf(DebtDirections.I_OWE, DebtDirections.OWED_TO_ME).forEach { direction ->
                AppFilterChip(
                    selected = selected == direction,
                    onClick = { onSelect(direction) },
                    label = stringResource(debtDirectionLabelRes(direction)),
                )
            }
        }
    }
}
