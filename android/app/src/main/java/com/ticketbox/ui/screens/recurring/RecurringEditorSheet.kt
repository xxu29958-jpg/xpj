package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppFormFieldGroup
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionFeedback
import com.ticketbox.ui.components.AppSheetActionFeedbackState
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.selectedDateMillisFromIso
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.RecurringItemActions
import com.ticketbox.viewmodel.RecurringUiState

/** 编辑器打开目标：新建，或编辑某条已发布项（active/paused 才会进来，archived 不给编辑）。 */
internal sealed interface RecurringEditorTarget {
    data object Create : RecurringEditorTarget
    data class Edit(val item: RecurringItem) : RecurringEditorTarget
}

internal data class RecurringEditorEnvironment(
    val currencyDisplay: CurrencyDisplay,
    val conflict: RecurringConflictModel?,
    val onDismiss: () -> Unit,
)

/** 提交等待态：error 非空 = 本地校验或 Danger 落定；awaiting = 已发起等受理。 */
private data class RecurringSubmitUi(
    val awaiting: Boolean = false,
    val sawLoading: Boolean = false,
    val error: String? = null,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun RecurringEditorSheetHost(
    target: RecurringEditorTarget?,
    uiState: RecurringUiState,
    environment: RecurringEditorEnvironment,
    actions: RecurringItemActions,
    onConflictAction: (RecurringConflictModel) -> Unit,
) {
    if (target == null) return
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = environment.onDismiss, sheetState = sheetState) {
        RecurringEditorSheet(
            target = target,
            uiState = uiState,
            actions = actions,
            environment = environment,
            onConflictAction = onConflictAction,
        )
    }
}

/**
 * 添加 / 编辑固定支出共用表单。不乐观关闭：提交后等 ViewModel 落定，成功（含
 * Queued 待同步）才关；失败保留表单亮错误。撞单（recurring_item_conflict）时
 * 冲突块直接给「查看/编辑现有记录」「恢复这条记录」出口。
 */
@Composable
internal fun RecurringEditorSheet(
    target: RecurringEditorTarget,
    uiState: RecurringUiState,
    actions: RecurringItemActions,
    environment: RecurringEditorEnvironment,
    onConflictAction: (RecurringConflictModel) -> Unit,
) {
    val editing = (target as? RecurringEditorTarget.Edit)?.item
    // 与 IncomePlan 表单同一约定：display home 仅作展示兜底，写面由 VM 账本 binding 守门。
    val currency = environment.currencyDisplay.homeCurrency
    val fieldKey = editing?.publicId ?: "create"
    var merchant by rememberSaveable(fieldKey) { mutableStateOf(editing?.merchant.orEmpty()) }
    var amountText by rememberSaveable(fieldKey) { mutableStateOf(editing?.let { formatAmountInput(it.baselineAmountCents, currency) } ?: "") }
    var dateIso by rememberSaveable(fieldKey) { mutableStateOf<String?>(editing?.nextExpectedDate ?: recurringDefaultNextDate()) }
    var dateTouched by rememberSaveable(fieldKey) { mutableStateOf(false) }
    var showDatePicker by rememberSaveable(fieldKey) { mutableStateOf(false) }
    var submitUi by remember(fieldKey) { mutableStateOf(RecurringSubmitUi()) }
    val merchantError = stringResource(R.string.recurring_form_error_merchant)
    val amountError = stringResource(R.string.recurring_form_error_amount)
    RecurringSubmitSettleEffect(uiState, submitUi, uiState.message?.asString(), { submitUi = it }, environment.onDismiss)

    fun submit() {
        fun startSubmit(call: () -> Unit) {
            submitUi = RecurringSubmitUi(awaiting = true)
            call()
        }
        val input = RecurringFormInput(merchant, amountText, dateTouched, dateIso)
        when (val result = resolveRecurringFormSubmit(editing, input, currency)) {
            is RecurringFormSubmit.Invalid -> submitUi = RecurringSubmitUi(
                error = if (result.reason == RecurringFormInvalid.Merchant) merchantError else amountError,
            )
            RecurringFormSubmit.DismissUnchanged -> environment.onDismiss()
            is RecurringFormSubmit.Create -> startSubmit { actions.onCreate(result.draft) }
            is RecurringFormSubmit.Edit -> startSubmit { actions.onEdit(result.item, result.patch) }
        }
    }

    RecurringEditorForm(
        title = stringResource(if (editing == null) R.string.recurring_form_title_create else R.string.recurring_form_title_edit),
        state = RecurringEditorFormState(
            merchant = merchant,
            // Candidate identity suppresses the already-claimed suggestion.
            // Cross-merchant reassignment needs a separate provenance owner;
            // this editor keeps the name visible and the other fields usable.
            merchantEditable = editing == null || editing.source == "manual",
            amountText = amountText,
            currency = currency,
            dateIso = dateIso,
            showDatePicker = showDatePicker,
            awaiting = submitUi.awaiting,
        ),
        callbacks = RecurringEditorFormCallbacks(
            onMerchant = { merchant = it },
            onAmount = { amountText = it },
            date = RecurringDateCallbacks(
                onPick = { showDatePicker = true },
                onClear = { dateIso = null; dateTouched = true },
                onSelect = { selected -> dateIso = selected; dateTouched = true; showDatePicker = false },
                onDismiss = { showDatePicker = false },
            ),
            onSubmit = ::submit,
            onCancel = environment.onDismiss,
        ),
        feedback = RecurringEditorFeedback(submitUi.error, environment.conflict, onConflictAction),
    )
}

@Composable
private fun RecurringSubmitSettleEffect(
    uiState: RecurringUiState,
    submitUi: RecurringSubmitUi,
    messageText: String?,
    onSubmitUiChange: (RecurringSubmitUi) -> Unit,
    onAccepted: () -> Unit,
) {
    LaunchedEffect(uiState.loading, uiState.message) {
        if (!submitUi.awaiting) return@LaunchedEffect
        val step = recurringSubmitStep(
            awaiting = submitUi.awaiting,
            sawLoading = submitUi.sawLoading,
            loading = uiState.loading,
            hasMessage = uiState.message != null,
            danger = uiState.messageTone == MessageTone.Danger,
        )
        when (step.outcome) {
            RecurringSubmitSettle.Failure -> onSubmitUiChange(RecurringSubmitUi(error = messageText))
            RecurringSubmitSettle.Accepted -> onAccepted()
            null -> if (step.sawLoading != submitUi.sawLoading) {
                onSubmitUiChange(submitUi.copy(sawLoading = step.sawLoading))
            }
        }
    }
}

internal data class RecurringEditorFormState(
    val merchant: String,
    val merchantEditable: Boolean,
    val amountText: String,
    val currency: CurrencyCode,
    val dateIso: String?,
    val showDatePicker: Boolean,
    val awaiting: Boolean,
)

internal data class RecurringDateCallbacks(
    val onPick: () -> Unit,
    val onClear: () -> Unit,
    val onSelect: (String) -> Unit,
    val onDismiss: () -> Unit,
)

internal data class RecurringEditorFormCallbacks(
    val onMerchant: (String) -> Unit,
    val onAmount: (String) -> Unit,
    val date: RecurringDateCallbacks,
    val onSubmit: () -> Unit,
    val onCancel: () -> Unit,
)

internal data class RecurringEditorFeedback(
    val errorText: String?,
    val conflict: RecurringConflictModel?,
    val onConflictAction: (RecurringConflictModel) -> Unit,
)

@Composable
private fun RecurringEditorForm(
    title: String,
    state: RecurringEditorFormState,
    callbacks: RecurringEditorFormCallbacks,
    feedback: RecurringEditorFeedback,
) {
    RecurringEditorDateDialogHost(
        showPicker = state.showDatePicker,
        currentIso = state.dateIso,
        onSelect = callbacks.date.onSelect,
        onDismiss = callbacks.date.onDismiss,
    )
    AppSheetScaffold(
        title = title,
        subtitle = stringResource(R.string.recurring_form_subtitle),
    ) {
        if (state.merchantEditable) {
            AppTextInput(
                state = AppTextInputState(
                    label = stringResource(R.string.recurring_form_merchant_label),
                    value = state.merchant,
                    placeholder = stringResource(R.string.recurring_form_merchant_placeholder),
                    enabled = !state.awaiting,
                ),
                actions = AppTextInputActions(onValueChange = callbacks.onMerchant),
                modifier = Modifier.fillMaxWidth(),
            )
        } else {
            AppFormFieldGroup(label = stringResource(R.string.recurring_form_merchant_label)) {
                Text(text = state.merchant, style = MaterialTheme.typography.bodyLarge)
                Text(
                    text = stringResource(R.string.recurring_form_observed_merchant_hint),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        AppAmountInput(
            state = AppAmountInputState(
                label = stringResource(R.string.recurring_form_amount_label),
                currency = state.currency,
                value = state.amountText,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                enabled = !state.awaiting,
                isError = feedback.errorText == stringResource(R.string.recurring_form_error_amount),
            ),
            actions = AppAmountInputActions(onValueChange = callbacks.onAmount),
        )
        RecurringDateField(
            dateIso = state.dateIso,
            enabled = !state.awaiting,
            onPick = callbacks.date.onPick,
            onClear = callbacks.date.onClear,
        )
        RecurringEditorFeedbackSlot(
            feedback = feedback,
            awaiting = state.awaiting,
            onSubmit = callbacks.onSubmit,
            onCancel = callbacks.onCancel,
        )
    }
}

@Composable
private fun RecurringEditorFeedbackSlot(
    feedback: RecurringEditorFeedback,
    awaiting: Boolean,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        feedback.conflict?.let { RecurringConflictBlock(model = it, onAction = feedback.onConflictAction) }
        AppSheetActionFeedback(
            state = AppSheetActionFeedbackState(
                // 冲突块是更新、更具体的信号，避免和校验错双重红色。
                validationMessage = feedback.errorText.takeIf { feedback.conflict == null },
            ),
            primary = AppSheetAction(
                text = stringResource(
                    if (awaiting) R.string.recurring_form_saving else R.string.recurring_form_save,
                ),
                icon = Icons.Filled.Check,
                enabled = !awaiting,
                onClick = onSubmit,
            ),
            secondary = AppSheetAction(
                text = stringResource(R.string.common_cancel),
                enabled = !awaiting,
                onClick = onCancel,
            ),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RecurringEditorDateDialogHost(
    showPicker: Boolean,
    currentIso: String?,
    onSelect: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    if (!showPicker) return
    val pickerState = rememberDatePickerState(
        initialSelectedDateMillis = selectedDateMillisFromIso(currentIso),
    )
    DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(
                onClick = {
                    pickerState.selectedDateMillis
                        ?.let { onSelect(recurringPickerMillisToDateIso(it)) }
                        ?: onDismiss()
                },
            ) {
                Text(stringResource(R.string.common_confirm))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    ) {
        DatePicker(
            state = pickerState,
            title = {
                Text(
                    stringResource(R.string.recurring_form_date_picker_title),
                    modifier = Modifier.padding(
                        start = AppSpacing.cardPadding,
                        end = AppSpacing.compactGap,
                        top = AppSpacing.cardPaddingSmall,
                    ),
                )
            },
        )
    }
}

@Composable
private fun RecurringDateField(
    dateIso: String?,
    enabled: Boolean,
    onPick: () -> Unit,
    onClear: () -> Unit,
) {
    AppFormFieldGroup(label = stringResource(R.string.recurring_form_date_label)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = dateIso?.let { recurringDisplayDate(it) }
                        ?: stringResource(R.string.recurring_form_date_none),
                    style = MaterialTheme.typography.bodyLarge,
                )
                Text(
                    text = stringResource(
                        if (dateIso == null) {
                            R.string.recurring_form_date_hint_none
                        } else {
                            R.string.recurring_form_date_hint_set
                        },
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (dateIso != null) {
                TextButton(enabled = enabled, onClick = onClear) {
                    Text(stringResource(R.string.recurring_form_date_clear))
                }
            }
            AppSecondaryButton(
                text = stringResource(
                    if (dateIso == null) R.string.recurring_form_date_pick else R.string.recurring_form_date_change,
                ),
                enabled = enabled,
                onClick = onPick,
            )
        }
    }
}
