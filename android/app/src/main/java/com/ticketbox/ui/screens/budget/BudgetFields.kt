package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.viewmodel.BudgetCategoryInput

@Composable
internal fun MoneyField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    placeholder: String,
    modifier: Modifier = Modifier,
) {
    AppAmountInput(
        state = AppAmountInputState(
            label = label,
            currency = LocalCurrencyDisplay.current.homeCurrency,
            value = value,
            placeholder = placeholder,
        ),
        actions = AppAmountInputActions(onValueChange = onValueChange),
        modifier = modifier.fillMaxWidth(),
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
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.budget_field_category_label),
                value = row.category,
                placeholder = stringResource(R.string.budget_field_category_placeholder),
            ),
            actions = AppTextInputActions(onValueChange = { onChange(it, row.amount) }),
            modifier = Modifier.fillMaxWidth(),
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
