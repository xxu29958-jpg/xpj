package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimeInput
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.datePickerMillisToUtcIso
import com.ticketbox.ui.components.selectedDateMillisFromIso
import com.ticketbox.ui.components.selectedHourFromIso
import com.ticketbox.ui.components.selectedMinuteFromIso
import com.ticketbox.ui.components.timePickerToUtcIso

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ExpenseEditDatePicker(
    expenseTime: String,
    onSetExpenseTime: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val datePickerState = rememberDatePickerState(
        initialSelectedDateMillis = selectedDateMillisFromIso(expenseTime),
    )
    DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(
                onClick = {
                    datePickerState.selectedDateMillis?.let { selected ->
                        onSetExpenseTime(datePickerMillisToUtcIso(selected, expenseTime))
                    }
                    onDismiss()
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
            state = datePickerState,
            title = {
                Text(
                    stringResource(R.string.expense_edit_date_picker_title),
                    modifier = Modifier.padding(start = 24.dp, end = 12.dp, top = 16.dp),
                )
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ExpenseEditTimePicker(
    expenseTime: String,
    onSetExpenseTime: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val timePickerState = rememberTimePickerState(
        initialHour = selectedHourFromIso(expenseTime),
        initialMinute = selectedMinuteFromIso(expenseTime),
        is24Hour = true,
    )
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.expense_edit_time_picker_title)) },
        text = { TimeInput(state = timePickerState) },
        confirmButton = {
            TextButton(
                onClick = {
                    onSetExpenseTime(
                        timePickerToUtcIso(
                            hour = timePickerState.hour,
                            minute = timePickerState.minute,
                            currentIso = expenseTime,
                        ),
                    )
                    onDismiss()
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
    )
}

@Composable
internal fun ExpenseEditRejectDialog(
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.expense_edit_reject_dialog_title)) },
        text = { Text(stringResource(R.string.expense_edit_reject_dialog_body)) },
        confirmButton = {
            TextButton(
                onClick = {
                    onDismiss()
                    onConfirm()
                },
            ) {
                Text(
                    stringResource(R.string.expense_edit_reject_dialog_confirm_button),
                    color = MaterialTheme.colorScheme.error,
                )
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}

/**
 * ADR-0042 Slice E-2: paste the receipt text by hand and let the server parse it
 * into the empty draft fields (商家 / 金额 / 时间 / 分类 candidates). Distinct from
 * the OCR-retry button next to it, which re-runs the server OCR provider on the
 * stored image. The parsed result only fills EMPTY fields — that's enforced
 * server-side, so the copy just says so; nothing is overwritten.
 */
@Composable
internal fun ExpenseEditRecognizeTextDialog(
    onRecognize: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.expense_edit_recognize_dialog_title)) },
        text = {
            OutlinedTextField(
                value = text,
                // Cap at the server's max_length so we don't round-trip a body
                // the route will 422; ~20k chars is far past any real receipt.
                onValueChange = { if (it.length <= MAX_RECOGNIZE_TEXT_LENGTH) text = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.expense_edit_recognize_field_label)) },
                placeholder = { Text(stringResource(R.string.expense_edit_recognize_field_placeholder)) },
                supportingText = { Text(stringResource(R.string.expense_edit_recognize_supporting_text)) },
                maxLines = 8,
            )
        },
        confirmButton = {
            TextButton(
                enabled = text.isNotBlank(),
                onClick = { onRecognize(text) },
            ) {
                Text(stringResource(R.string.expense_edit_recognize_confirm_button))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}

private const val MAX_RECOGNIZE_TEXT_LENGTH = 20000
