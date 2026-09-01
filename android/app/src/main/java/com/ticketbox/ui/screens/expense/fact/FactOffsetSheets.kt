package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SheetValue
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.StreamOffsetKind
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputDecorations
import com.ticketbox.ui.components.AppTextInputEmphasis
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.expense.ExpenseEditSheetScaffold
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.ExpenseFactViewModel
import com.ticketbox.viewmodel.OffsetFormField
import com.ticketbox.viewmodel.OffsetFormState
import com.ticketbox.viewmodel.VoidOffsetFormState
import com.ticketbox.viewmodel.canSubmitOffset
import com.ticketbox.viewmodel.canSubmitVoidOffset
import com.ticketbox.viewmodel.closeOffsetSheet
import com.ticketbox.viewmodel.closeVoidOffsetSheet
import com.ticketbox.viewmodel.loadExpenseFactBundle
import com.ticketbox.viewmodel.submitOffset
import com.ticketbox.viewmodel.submitVoidOffset
import com.ticketbox.viewmodel.updateOffsetFormField
import com.ticketbox.viewmodel.updateOffsetKind
import com.ticketbox.viewmodel.updateVoidOffsetReason

/**
 * Refund/Chargeback/Reversal 纵向片：事实屏 offset sheet 托管（FactSheetHosts 的
 * offsets 部分，detekt 拆分）。登记 = 退款/拒付分段 + 金额/日期/原因；冲销无金额；
 * 撤销 = echo 目标 + 必填原因。conflict 三态（刷新中/刷新失败可重试/已刷新待核对）
 * 由 [FactOffsetSheetFeedback] 统一表达；supportingText 复用 quickMerchant 同形范式。
 *
 * saving 用户后置条件：Back/手势在 `saving=true` 时不得隐藏 sheet（草稿与 in-flight
 * feedback 不消失）——confirmValueChange 拒 Hidden，onDismissRequest 同步 no-op。
 * remaining 提示只在 bundle 真实 Loaded 时取自快照；Failed/Loading 明示暂不可用。
 */

@Composable
internal fun FactOffsetSheetHosts(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
    if (state.offsetForm.open) {
        FactOffsetFormSheet(state = state, viewModel = viewModel)
    }
    if (state.voidOffsetForm.open && state.voidOffsetForm.target != null) {
        FactVoidOffsetSheet(state = state, viewModel = viewModel)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FactOffsetFormSheet(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
    val form = state.offsetForm
    val reversal = !form.kind.isMoneyEvent
    val sheetState = rememberModalBottomSheetState(
        skipPartiallyExpanded = true,
        confirmValueChange = { target -> !form.saving || target != SheetValue.Hidden },
    )
    ModalBottomSheet(
        onDismissRequest = { if (!form.saving) viewModel.closeOffsetSheet() },
        sheetState = sheetState,
    ) {
        ExpenseEditSheetScaffold(
            title = stringResource(
                if (reversal) {
                    R.string.expense_offset_sheet_title_reversal
                } else {
                    R.string.expense_offset_sheet_title_refund
                },
            ),
            subtitle = stringResource(
                if (reversal) {
                    R.string.expense_offset_sheet_subtitle_reversal
                } else {
                    R.string.expense_offset_sheet_subtitle_refund
                },
            ),
        ) {
            OffsetFormContent(state = state, viewModel = viewModel, reversal = reversal)
        }
    }
}

@Composable
private fun OffsetFormContent(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
    reversal: Boolean,
) {
    val form = state.offsetForm
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        FactOffsetSheetFeedback(
            conflictMessage = form.conflictMessage,
            submitError = form.submitError,
            refreshing = form.refreshingAfterConflict,
            refreshFailed = state.factBundleLoadState == ExpenseDetailDataLoadState.Failed,
            onRetryRefresh = viewModel::loadExpenseFactBundle,
        )
        if (reversal) {
            Text(
                text = stringResource(R.string.expense_offset_reversal_explainer),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
        } else {
            OffsetKindSegmented(
                kind = form.kind,
                enabled = !form.saving,
                onSelect = viewModel::updateOffsetKind,
            )
            OffsetAmountField(state = state, viewModel = viewModel)
        }
        OffsetTextFields(form = form, viewModel = viewModel)
        AppSheetActionRow(
            primary = AppSheetAction(
                text = stringResource(
                    if (form.saving) {
                        R.string.expense_offset_saving
                    } else if (reversal) {
                        R.string.expense_offset_submit_reversal
                    } else {
                        R.string.expense_offset_submit_refund
                    },
                ),
                enabled = viewModel.canSubmitOffset(),
                onClick = viewModel::submitOffset,
            ),
            secondary = AppSheetAction(
                text = stringResource(R.string.common_cancel),
                enabled = !form.saving,
                onClick = viewModel::closeOffsetSheet,
            ),
        )
    }
}

/** conflict 三态：刷新中（禁提交）/ 刷新失败（可重试出口）/ 已刷新（banner 提示核对）。 */
@Composable
private fun FactOffsetSheetFeedback(
    conflictMessage: UiText?,
    submitError: UiText?,
    refreshing: Boolean,
    refreshFailed: Boolean,
    onRetryRefresh: () -> Unit,
) {
    if (refreshing) {
        if (refreshFailed) {
            AppStatusBanner(
                message = UiText.res(R.string.expense_offset_conflict_refresh_failed),
                tone = MessageTone.Danger,
            )
            AppSecondaryButton(
                text = stringResource(R.string.common_retry),
                modifier = Modifier.fillMaxWidth(),
                onClick = onRetryRefresh,
            )
        } else {
            AppStatusBanner(
                message = UiText.res(R.string.expense_offset_conflict_refreshing),
                tone = MessageTone.Info,
                announceUpdates = false,
            )
        }
        return
    }
    conflictMessage?.let { AppStatusBanner(message = it, tone = MessageTone.Danger) }
    submitError?.let { AppStatusBanner(message = it, tone = MessageTone.Danger) }
}

@Composable
private fun OffsetKindSegmented(
    kind: StreamOffsetKind,
    enabled: Boolean,
    onSelect: (StreamOffsetKind) -> Unit,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
        FilterChip(
            selected = kind == StreamOffsetKind.Refund,
            onClick = { onSelect(StreamOffsetKind.Refund) },
            label = { Text(text = stringResource(R.string.expense_offset_kind_refund)) },
            enabled = enabled,
        )
        FilterChip(
            selected = kind == StreamOffsetKind.Chargeback,
            onClick = { onSelect(StreamOffsetKind.Chargeback) },
            label = { Text(text = stringResource(R.string.expense_offset_kind_chargeback)) },
            enabled = enabled,
        )
    }
}

@Composable
private fun OffsetAmountField(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
    val form = state.offsetForm
    val expense = state.expense ?: return
    // remaining 提示只认真实 Loaded 的 bundle 快照；Failed/Loading 明示暂不可用。
    val summary = (state.factBundle?.financialSummary).takeIf {
        state.factBundleLoadState == ExpenseDetailDataLoadState.Loaded
    }
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(
                R.string.expense_offset_amount_label,
                expense.originalCurrencyCode.storageKey,
            ),
            value = form.amountText,
            isError = form.amountError != null,
            emphasis = AppTextInputEmphasis.Amount,
            enabled = !form.saving,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        ),
        actions = AppTextInputActions(
            onValueChange = { viewModel.updateOffsetFormField(OffsetFormField.Amount, it) },
        ),
        decorations = AppTextInputDecorations(
            supportingText = offsetAmountSupportingText(
                form = form,
                summary = summary,
                currency = expense.originalCurrencyCode,
            ),
        ),
    )
}

@Composable
private fun OffsetTextFields(
    form: OffsetFormState,
    viewModel: ExpenseFactViewModel,
) {
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.expense_offset_date_label),
            value = form.accountingDate,
            placeholder = stringResource(R.string.expense_offset_date_placeholder),
            isError = form.dateError != null,
            enabled = !form.saving,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
        ),
        actions = AppTextInputActions(
            onValueChange = { viewModel.updateOffsetFormField(OffsetFormField.AccountingDate, it) },
        ),
        decorations = AppTextInputDecorations(
            supportingText = offsetFieldErrorText(form.dateError),
        ),
    )
    val reasonPlaceholder = stringResource(
        when (form.kind) {
            StreamOffsetKind.Refund -> R.string.expense_offset_reason_placeholder_refund
            StreamOffsetKind.Chargeback -> R.string.expense_offset_reason_placeholder_chargeback
            StreamOffsetKind.Reversal -> R.string.expense_offset_reason_placeholder_reversal
        },
    )
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.expense_offset_reason_label),
            value = form.reason,
            placeholder = reasonPlaceholder,
            enabled = !form.saving,
            singleLine = false,
            minLines = 2,
        ),
        actions = AppTextInputActions(
            onValueChange = { viewModel.updateOffsetFormField(OffsetFormField.Reason, it) },
        ),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FactVoidOffsetSheet(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
    val form = state.voidOffsetForm
    val target = form.target ?: return
    val sheetState = rememberModalBottomSheetState(
        skipPartiallyExpanded = true,
        confirmValueChange = { targetValue -> !form.saving || targetValue != SheetValue.Hidden },
    )
    ModalBottomSheet(
        onDismissRequest = { if (!form.saving) viewModel.closeVoidOffsetSheet() },
        sheetState = sheetState,
    ) {
        ExpenseEditSheetScaffold(
            title = stringResource(R.string.expense_offset_void_title),
            subtitle = stringResource(
                R.string.expense_offset_void_explainer,
                offsetKindLabel(target.kind),
            ),
        ) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                FactOffsetSheetFeedback(
                    conflictMessage = form.conflictMessage,
                    submitError = form.submitError,
                    refreshing = form.refreshingAfterConflict,
                    refreshFailed = state.factBundleLoadState == ExpenseDetailDataLoadState.Failed,
                    onRetryRefresh = viewModel::loadExpenseFactBundle,
                )
                VoidOffsetEcho(target = target)
                VoidOffsetReasonInput(form = form, viewModel = viewModel)
                AppSheetActionRow(
                    primary = AppSheetAction(
                        text = stringResource(
                            if (form.saving) {
                                R.string.expense_offset_saving
                            } else {
                                R.string.expense_offset_void_submit
                            },
                        ),
                        enabled = viewModel.canSubmitVoidOffset(),
                        onClick = viewModel::submitVoidOffset,
                    ),
                    secondary = AppSheetAction(
                        text = stringResource(R.string.common_cancel),
                        enabled = !form.saving,
                        onClick = viewModel::closeVoidOffsetSheet,
                    ),
                )
            }
        }
    }
}

@Composable
private fun VoidOffsetReasonInput(form: VoidOffsetFormState, viewModel: ExpenseFactViewModel) {
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.expense_offset_void_reason_label),
            value = form.reason,
            placeholder = stringResource(R.string.expense_offset_void_reason_placeholder),
            enabled = !form.saving,
            singleLine = false,
            minLines = 2,
        ),
        actions = AppTextInputActions(onValueChange = viewModel::updateVoidOffsetReason),
    )
}

@Composable
private fun VoidOffsetEcho(target: ExpenseOffsetFact) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StatusPill(text = offsetKindLabel(target.kind), active = false)
        offsetInflowAmountText(target)?.let { amountText ->
            Text(
                text = amountText,
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
    Text(
        text = listOf(target.accountingDate, target.reason)
            .filter { it.isNotBlank() }
            .joinToString(" · "),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
}
