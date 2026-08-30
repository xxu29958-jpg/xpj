package com.ticketbox.ui.screens.recurring

import androidx.annotation.StringRes
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
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppFormFieldGroup
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionFeedback
import com.ticketbox.ui.components.AppSheetActionFeedbackState
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.selectedDateMillisFromIso
import com.ticketbox.ui.design.AppSpacing

internal data class RecurringEditorFormState(
    val merchant: String,
    val merchantEditable: Boolean,
    val amountText: String,
    val currency: CurrencyCode,
    val dateIso: String?,
    val showDatePicker: Boolean,
    val awaiting: Boolean,
    val draftEnabled: Boolean,
    val primaryText: String,
    val primaryEnabled: Boolean,
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
    val conflictStatus: Pair<String, MessageTone>?,
    val overlaps: List<RecurringOverlapComparison>,
    val onConflictAction: (RecurringConflictModel) -> Unit,
)

@Composable
internal fun RecurringEditorForm(
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
                    enabled = state.draftEnabled,
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
                enabled = state.draftEnabled,
                isError = feedback.errorText == stringResource(R.string.recurring_form_error_amount),
            ),
            actions = AppAmountInputActions(onValueChange = callbacks.onAmount),
        )
        RecurringDateField(
            dateIso = state.dateIso,
            enabled = state.draftEnabled,
            onPick = callbacks.date.onPick,
            onClear = callbacks.date.onClear,
        )
        RecurringEditorFeedbackSlot(
            feedback = feedback,
            state = state,
            callbacks = callbacks,
        )
    }
}

@Composable
private fun RecurringEditorFeedbackSlot(
    feedback: RecurringEditorFeedback,
    state: RecurringEditorFormState,
    callbacks: RecurringEditorFormCallbacks,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        feedback.conflict?.let { RecurringConflictBlock(model = it, onAction = feedback.onConflictAction) }
        feedback.conflictStatus?.let { (text, tone) ->
            AppStatusBanner(message = UiText.raw(text), tone = tone)
        }
        if (feedback.overlaps.isNotEmpty()) {
            RecurringOverlapComparisonSection(feedback.overlaps, state.currency)
        }
        AppSheetActionFeedback(
            state = AppSheetActionFeedbackState(
                validationMessage = feedback.errorText.takeIf {
                    feedback.conflict == null && feedback.conflictStatus == null
                },
            ),
            primary = AppSheetAction(
                text = state.primaryText,
                icon = Icons.Filled.Check,
                enabled = state.primaryEnabled,
                onClick = callbacks.onSubmit,
            ),
            secondary = AppSheetAction(
                text = stringResource(R.string.common_cancel),
                enabled = !state.awaiting,
                onClick = callbacks.onCancel,
            ),
        )
    }
}

@Composable
private fun RecurringOverlapComparisonSection(
    comparisons: List<RecurringOverlapComparison>,
    currency: CurrencyCode,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        Text(
            text = stringResource(R.string.recurring_form_conflict_compare_title),
            style = MaterialTheme.typography.titleSmall,
        )
        comparisons.forEach { comparison ->
            AppFormFieldGroup(label = stringResource(comparison.field.labelRes())) {
                Text(
                    text = stringResource(
                        R.string.recurring_form_conflict_current_value,
                        comparison.value.currentDisplay(currency),
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    text = stringResource(
                        R.string.recurring_form_conflict_draft_value,
                        comparison.value.draftDisplay(currency),
                    ),
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

@StringRes
private fun RecurringEditField.labelRes(): Int = when (this) {
    RecurringEditField.Merchant -> R.string.recurring_form_merchant_label
    RecurringEditField.Amount -> R.string.recurring_form_amount_label
    RecurringEditField.Date -> R.string.recurring_form_date_label
}

@Composable
private fun RecurringOverlapValue.currentDisplay(currency: CurrencyCode): String = when (this) {
    is RecurringOverlapValue.Text -> current
    is RecurringOverlapValue.Amount -> formatDisplayAmount(
        currentCents,
        CurrencyDisplay(homeCurrency = currency),
    )
    is RecurringOverlapValue.RawAmount -> formatDisplayAmount(
        currentCents,
        CurrencyDisplay(homeCurrency = currency),
    )
    is RecurringOverlapValue.Date -> currentIso?.let(::recurringDisplayDate)
        ?: stringResource(R.string.recurring_form_date_none)
}

@Composable
private fun RecurringOverlapValue.draftDisplay(currency: CurrencyCode): String = when (this) {
    is RecurringOverlapValue.Text -> draft
    is RecurringOverlapValue.Amount -> formatDisplayAmount(
        draftCents,
        CurrencyDisplay(homeCurrency = currency),
    )
    is RecurringOverlapValue.RawAmount -> draftText.ifBlank {
        stringResource(R.string.recurring_form_conflict_value_unavailable)
    }
    is RecurringOverlapValue.Date -> draftIso?.let(::recurringDisplayDate)
        ?: stringResource(R.string.recurring_form_date_none)
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
