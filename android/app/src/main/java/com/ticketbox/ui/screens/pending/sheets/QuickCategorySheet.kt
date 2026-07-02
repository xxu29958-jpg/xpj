package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardCapitalization
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun QuickCategorySheetContent(
    expense: Expense,
    options: List<String>,
    chrome: ReviewSheetChrome,
    onSave: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val saving = chrome.saving
    val initial = expense.category.takeIf { it.isNotBlank() } ?: options.firstOrNull().orEmpty()
    var selected by remember(expense.id) { mutableStateOf(initial) }
    var custom by remember(expense.id) { mutableStateOf("") }

    ReviewSheetScaffold(
        title = stringResource(R.string.quick_category_sheet_title),
        subtitle = stringResource(R.string.quick_category_sheet_hint),
        chrome = chrome,
    ) {
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap + AppSpacing.tinyGap),
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
            label = { Text(stringResource(R.string.quick_category_custom_label)) },
            modifier = Modifier.fillMaxWidth(),
            enabled = !saving,
        )

        ReviewSheetStatusMessage(chrome = chrome)

        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppSecondaryButton(
                text = stringResource(R.string.common_cancel),
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
                Text(
                    if (saving) {
                        stringResource(R.string.common_saving)
                    } else {
                        stringResource(R.string.quick_category_save_button)
                    },
                )
            }
        }
    }
}
