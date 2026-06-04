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
import androidx.compose.ui.unit.dp
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
                Text("确定")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
            }
        },
    ) {
        DatePicker(
            state = datePickerState,
            title = {
                Text(
                    "选择日期",
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
        title = { Text("选择时间") },
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
                Text("确定")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
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
        title = { Text("删除这笔账单？") },
        text = { Text("删除后会标记为已拒绝，不会进入账本。") },
        confirmButton = {
            TextButton(
                onClick = {
                    onDismiss()
                    onConfirm()
                },
            ) {
                Text("确定删除", color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
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
        title = { Text("粘贴文字识别") },
        text = {
            OutlinedTextField(
                value = text,
                // Cap at the server's max_length so we don't round-trip a body
                // the route will 422; ~20k chars is far past any real receipt.
                onValueChange = { if (it.length <= MAX_RECOGNIZE_TEXT_LENGTH) text = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("粘贴小票文字") },
                placeholder = { Text("例如：星巴克 拿铁 ¥35 2026-05-20 …") },
                supportingText = { Text("识别结果只会填入空白项，不会覆盖你已填写的内容") },
                maxLines = 8,
            )
        },
        confirmButton = {
            TextButton(
                enabled = text.isNotBlank(),
                onClick = { onRecognize(text) },
            ) {
                Text("识别")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
            }
        },
    )
}

private const val MAX_RECOGNIZE_TEXT_LENGTH = 20000
