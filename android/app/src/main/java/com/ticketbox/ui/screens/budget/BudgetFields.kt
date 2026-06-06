package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.BudgetCategoryInput

@Composable
internal fun MoneyField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    placeholder: String,
    modifier: Modifier = Modifier,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.fillMaxWidth(),
        label = { Text(label) },
        placeholder = { Text(placeholder) },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        singleLine = true,
    )
}

@Composable
internal fun CategoryInputRow(
    row: BudgetCategoryInput,
    canRemove: Boolean,
    onChange: (String, String) -> Unit,
    onRemove: () -> Unit,
) {
    val trimmedCategory = row.category.takeIf { it.isNotBlank() }
    val removeDescription = if (trimmedCategory != null) {
        stringResource(R.string.budget_field_remove_category_named, trimmedCategory)
    } else {
        stringResource(R.string.budget_field_remove_category)
    }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        OutlinedTextField(
            value = row.category,
            onValueChange = { onChange(it, row.amount) },
            modifier = Modifier.fillMaxWidth(),
            label = { Text(stringResource(R.string.budget_field_category_label)) },
            placeholder = { Text(stringResource(R.string.budget_field_category_placeholder)) },
            singleLine = true,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            MoneyField(
                value = row.amount,
                onValueChange = { onChange(row.category, it) },
                label = stringResource(R.string.budget_field_amount_label),
                placeholder = stringResource(R.string.budget_field_amount_placeholder),
                modifier = Modifier.weight(1f),
            )
            IconButton(
                enabled = canRemove,
                onClick = onRemove,
            ) {
                Icon(
                    Icons.Filled.DeleteOutline,
                    contentDescription = removeDescription,
                )
            }
        }
    }
}
