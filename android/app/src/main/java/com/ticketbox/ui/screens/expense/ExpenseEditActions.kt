package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
internal fun ExpenseEditPrimaryActions(
    saving: Boolean,
    allowSave: Boolean = true,
    onBack: () -> Unit,
    onSave: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        OutlinedButton(
            modifier = Modifier.weight(1f),
            enabled = !saving,
            onClick = onBack,
        ) {
            Text("返回")
        }
        if (allowSave) {
            Button(
                modifier = Modifier.weight(1f),
                enabled = !saving,
                onClick = onSave,
            ) {
                Text(if (saving) "保存中" else "保存")
            }
        }
    }
}

@Composable
internal fun ExpenseEditConfirmActions(
    saving: Boolean,
    allowConfirm: Boolean,
    allowReject: Boolean,
    onConfirm: () -> Unit,
    onRequestReject: () -> Unit,
) {
    if (!allowConfirm && !allowReject) return
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (allowConfirm) {
            Button(
                modifier = Modifier.weight(1f),
                enabled = !saving,
                onClick = onConfirm,
            ) {
                Text("确认入账")
            }
        }
        if (allowReject) {
            OutlinedButton(
                modifier = Modifier.weight(if (allowConfirm) 0.72f else 1f),
                enabled = !saving,
                colors = ButtonDefaults.outlinedButtonColors(
                    contentColor = MaterialTheme.colorScheme.error,
                ),
                onClick = onRequestReject,
            ) {
                Text("删除")
            }
        }
    }
}
