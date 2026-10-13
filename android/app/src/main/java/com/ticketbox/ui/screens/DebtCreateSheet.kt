package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SheetState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppFilterChipOptions
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
import com.ticketbox.viewmodel.updateDraftPrincipalDate

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun DebtAddSheet(
    state: DebtListUiState,
    viewModel: DebtListViewModel,
    sheetState: SheetState,
    onClose: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = { if (!state.isSubmitting) onClose() }, sheetState = sheetState) {
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
    val editable = state.canModify && !state.isSubmitting && !state.publicationUnverified
    AppSheetScaffold(
        title = stringResource(R.string.debt_create_sheet_title),
        subtitle = stringResource(R.string.debt_creation_subtitle),
        actions = {
            DebtCreateStatus(state = state, onRetry = viewModel::refresh)
            AppSheetActionRow(
                primary = AppSheetAction(
                    text = if (state.isSubmitting) {
                        stringResource(R.string.debt_create_submitting)
                    } else if (state.publicationUnverified) {
                        stringResource(R.string.debt_creation_check_local)
                    } else {
                        stringResource(R.string.debt_create_save)
                    },
                    onClick = onSubmit,
                    // 账本币种未确认（初始/切换加载未成功）禁用创建：兜底 CNY 口径提交到
                    // JPY/KRW 账本会放大 100×（PR#255 P1-3，VM submitDraft 另有同条件防线）。
                    enabled = state.canSubmitCreation,
                ),
                secondary = AppSheetAction(
                    text = stringResource(R.string.debt_creation_keep_exit),
                    onClick = onCancel,
                    enabled = !state.isSubmitting,
                ),
            )
        },
    ) {
        DebtDirectionField(selected = draft.direction, enabled = editable, onSelect = viewModel::updateDraftDirection)
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.debt_create_label_counterparty),
                value = draft.counterpartyLabel,
                enabled = editable,
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
                enabled = editable,
            ),
            actions = AppAmountInputActions(onValueChange = viewModel::updateDraftAmount),
            modifier = Modifier.fillMaxWidth(),
        )
        DebtPrincipalDateField(state, viewModel)
        DebtKindCreateField(selected = draft.kind, enabled = editable, onSelect = viewModel::updateDraftKind)
        DebtDraftDetails(draft, editable, viewModel)
        TextButton(onClick = { viewModel.discardDraft(); onCancel() }, enabled = editable) {
            Text(stringResource(R.string.debt_creation_discard_original))
        }
    }
}

@Composable
private fun DebtDraftDetails(draft: DebtDraftUi, editable: Boolean, viewModel: DebtListViewModel) {
    var expanded by rememberSaveable { mutableStateOf(draft.note.isNotBlank() || draft.kind == DebtKinds.INSTALLMENT) }
    LaunchedEffect(draft.kind) { if (draft.kind == DebtKinds.INSTALLMENT) expanded = true }
    TextButton(onClick = { expanded = !expanded }, modifier = Modifier.fillMaxWidth()) {
        Text(stringResource(if (expanded) R.string.debt_creation_details_collapse else R.string.debt_creation_details_expand))
    }
    if (expanded) {
        DebtInstallmentCountField(kind = draft.kind, countInput = draft.installmentCountInput,
            enabled = editable, onValueChange = viewModel::updateDraftInstallmentCount)
        DebtInstallmentPeriodField(kind = draft.kind, periodInput = draft.installmentPeriodInput,
            enabled = editable, onValueChange = viewModel::updateDraftInstallmentPeriod)
        DebtContextField(draft = draft, enabled = editable, onValueChange = viewModel::updateDraftNote)
    }
}

@Composable
private fun DebtPrincipalDateField(state: DebtListUiState, viewModel: DebtListViewModel) {
    val calendars = com.ticketbox.ui.screens.expense.LocalLedgerCalendarRepository.current
    LaunchedEffect(viewModel, calendars) { viewModel.refresh(calendars) }
    DebtDateField(state.addDraft.principalDate, state.canModify && !state.isSubmitting && !state.publicationUnverified, R.string.debt_principal_date_label,
        onChange = viewModel::updateDraftPrincipalDate)
    Text(stringResource(R.string.debt_principal_date_hint), style = MaterialTheme.typography.bodySmall)
    if (state.addDraft.calendarRevision == null) {
        TextButton(onClick = { viewModel.refresh(calendars) }, enabled = !state.isSubmitting) {
            Text(stringResource(R.string.debt_principal_calendar_retry))
        }
    }
}

/** Publication, permission and read capability are different states; every failure keeps the original. */
@Composable
private fun DebtCreateStatus(state: DebtListUiState, onRetry: () -> Unit) {
    state.addDraft.validationError?.let { AppStatusBanner(message = it, tone = MessageTone.Danger) }
    if (state.publicationUnverified) {
        AppStatusBanner(message = UiText.res(R.string.debt_creation_local_unverified), tone = MessageTone.Info)
    } else if (!state.canModify) {
        AppStatusBanner(message = UiText.res(R.string.debt_creation_readonly_original), tone = MessageTone.Info)
    }
    if (state.homeCurrencyResolved || state.isLoading) return
    Row(verticalAlignment = Alignment.CenterVertically) {
        AppStatusBanner(
            message = UiText.res(R.string.debt_create_currency_unconfirmed),
            tone = MessageTone.Info,
            modifier = Modifier.weight(1f),
        )
        TextButton(onClick = onRetry, enabled = !state.isSubmitting) {
            Text(stringResource(R.string.common_retry))
        }
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
@OptIn(ExperimentalLayoutApi::class)
private fun DebtDirectionField(selected: String, enabled: Boolean, onSelect: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            stringResource(R.string.debt_create_label_direction),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            listOf(DebtDirections.I_OWE, DebtDirections.OWED_TO_ME).forEach { direction ->
                AppFilterChip(
                    selected = selected == direction,
                    onClick = { onSelect(direction) },
                    label = stringResource(if (direction == DebtDirections.I_OWE)
                        R.string.debt_creation_i_owe else R.string.debt_creation_owed_to_me),
                    options = AppFilterChipOptions(enabled = enabled),
                )
            }
        }
    }
}
