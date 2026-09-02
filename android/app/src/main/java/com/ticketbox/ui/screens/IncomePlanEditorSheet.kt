package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SheetValue
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.viewmodel.IncomePlanDraftField
import com.ticketbox.viewmodel.IncomePlanEditUiState
import com.ticketbox.viewmodel.IncomePlanEditViewModel

/** 编辑器回调组：共享表单两组 + 提交/取消/归档（归档收编辑器内，可逆——回收站可恢复）。 */
internal data class IncomePlanEditSheetCallbacks(
    val fields: IncomePlanDraftFieldCallbacks,
    val choices: IncomePlanDraftChoiceCallbacks,
    val onSubmit: () -> Unit,
    val onCancel: () -> Unit,
    val onArchive: () -> Unit,
)

/** 编辑会话宿主：会话在才挂抽屉；滑走/返回 = dismiss（草稿即弃，不产生写）。 */
@Composable
internal fun IncomePlanEditSheetHost(
    state: IncomePlanEditUiState,
    currency: CurrencyDisplay,
    editViewModel: IncomePlanEditViewModel,
) {
    if (state.session == null) return
    IncomePlanBusyGuardedSheet(
        isSubmitting = state.isSubmitting,
        onDismiss = editViewModel::dismiss,
    ) {
        EditIncomePlanSheet(
            state = state,
            currency = currency,
            callbacks = IncomePlanEditSheetCallbacks(
                fields = IncomePlanDraftFieldCallbacks(
                    onLabel = { editViewModel.updateDraftField(IncomePlanDraftField.Label, it) },
                    onAmount = { editViewModel.updateDraftField(IncomePlanDraftField.Amount, it) },
                    onPayDay = { editViewModel.updateDraftField(IncomePlanDraftField.PayDay, it) },
                    onPreviousIncomeMonth = { editViewModel.shiftIncomeMonth(-1L) },
                    onNextIncomeMonth = { editViewModel.shiftIncomeMonth(1L) },
                    onRetryCurrency = editViewModel::retryCurrencyResolution,
                ),
                choices = IncomePlanDraftChoiceCallbacks(
                    onSourceType = { editViewModel.updateDraftChoice(source = it) },
                    onFrequency = { editViewModel.updateDraftChoice(frequency = it) },
                ),
                onSubmit = editViewModel::submit,
                onCancel = editViewModel::dismiss,
                onArchive = editViewModel::archiveFromEdit,
            ),
        )
    }
}

/** 编辑收入抽屉：共享表单 + 安静 danger 文字级归档 + 保存/取消；成功才由 ack 关闭。 */
@Composable
private fun EditIncomePlanSheet(
    state: IncomePlanEditUiState,
    currency: CurrencyDisplay,
    callbacks: IncomePlanEditSheetCallbacks,
) {
    val session = state.session ?: return
    AppSheetScaffold(title = stringResource(R.string.income_plan_edit_sheet_title)) {
        IncomePlanDraftForm(
            state = IncomePlanDraftFormState(
                draft = session.draft,
                isSubmitting = state.isSubmitting,
                currencyPending = state.currencyPending,
            ),
            currency = currency,
            fieldCallbacks = callbacks.fields,
            choiceCallbacks = callbacks.choices,
        )
        AppSheetActionRow(
            primary = AppAction(
                text = if (state.isSubmitting) {
                    stringResource(R.string.income_plan_sheet_submitting)
                } else {
                    stringResource(R.string.income_plan_sheet_save)
                },
                onClick = callbacks.onSubmit,
                enabled = !state.isSubmitting,
            ),
            secondary = AppAction(
                text = stringResource(R.string.common_cancel),
                onClick = callbacks.onCancel,
                enabled = !state.isSubmitting,
            ),
        )
        Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            TextButton(onClick = callbacks.onArchive, enabled = !state.isSubmitting) {
                Text(
                    stringResource(R.string.income_plan_card_archive_action),
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}

/**
 * 忙碌守门抽屉：onDismissRequest 守门不够——Back/手势仍会把 sheet 动画到 Hidden，
 * 遮住页面又不交还会话（真机反例 income-busy-hidden.png）。复用 RecurringEditorSheet
 * 的平台惯例：confirmValueChange 在忙碌时否决 Hidden，rememberUpdatedState 保证手势
 * 回调读到最新 busy；提交开始再 show() 一次，抢回刚好在 busy 置位前被预授权的 hide，
 * 失败结算不会把草稿留在隐藏抽屉里。抽成无 VM 组件以便真实 Compose 手势回归。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun IncomePlanBusyGuardedSheet(
    isSubmitting: Boolean,
    onDismiss: () -> Unit,
    content: @Composable () -> Unit,
) {
    val busy = rememberUpdatedState(isSubmitting)
    val sheetState = rememberModalBottomSheetState(
        confirmValueChange = { targetValue -> targetValue != SheetValue.Hidden || !busy.value },
    )
    LaunchedEffect(isSubmitting) {
        if (isSubmitting) sheetState.show()
    }
    ModalBottomSheet(
        onDismissRequest = { if (!isSubmitting) onDismiss() },
        sheetState = sheetState,
    ) {
        content()
    }
}
