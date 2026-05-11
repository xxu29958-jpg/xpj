package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSecondaryButton

/**
 * QuickCategory BottomSheet — slice 3 M2。
 * 仅触发 ViewModel.saveQuickCategory；不直接调用 Repository/API。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun QuickCategorySheetContent(
    expense: Expense,
    options: List<String>,
    saving: Boolean,
    onSave: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val initial = expense.category.takeIf { it.isNotBlank() } ?: options.firstOrNull().orEmpty()
    var selected by remember(expense.id) { mutableStateOf(initial) }
    var custom by remember(expense.id) { mutableStateOf("") }

    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("补一下分类", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black)
        Text(
            text = "选一个常用分类，或自定义。保存后不会自动确认入账。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )

        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            options.forEach { option ->
                AppFilterChip(
                    label = option,
                    selected = selected == option && custom.isBlank(),
                    onClick = {
                        selected = option
                        custom = ""
                    },
                )
            }
        }

        OutlinedTextField(
            value = custom,
            onValueChange = { custom = it.take(20) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None),
            label = { Text("或者输入新分类") },
            modifier = Modifier.fillMaxWidth(),
            enabled = !saving,
        )

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppSecondaryButton(
                text = "取消",
                modifier = Modifier.weight(1f),
                enabled = !saving,
                onClick = onDismiss,
            )
            Button(
                modifier = Modifier.weight(1f),
                enabled = !saving && (custom.trim().isNotEmpty() || selected.isNotBlank()),
                onClick = {
                    val choice = custom.trim().ifBlank { selected }.trim()
                    if (choice.isNotEmpty()) onSave(choice)
                },
            ) {
                Text(if (saving) "保存中" else "保存分类")
            }
        }
    }
}
