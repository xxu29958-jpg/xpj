package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.FxContract
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSolidCard

@Composable
internal fun ExpenseEditAmountField(
    amountText: String,
    onAmountChange: (String) -> Unit,
    enabled: Boolean = true,
) {
    OutlinedTextField(
        value = amountText,
        onValueChange = onAmountChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(stringResource(R.string.expense_edit_amount_field_label)) },
        placeholder = { Text("36.80") },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        singleLine = true,
        enabled = enabled,
    )
}

@Composable
internal fun ExpenseCurrencyFields(
    currency: CurrencyCode,
    onCurrencyChange: (CurrencyCode) -> Unit,
    originalAmountText: String,
    onOriginalAmountChange: (String) -> Unit,
    enabled: Boolean = true,
) {
    AppSolidCard {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(stringResource(R.string.expense_edit_currency_card_title), style = MaterialTheme.typography.titleSmall)
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(CurrencyCode.entries, key = { it.storageKey }) { code ->
                    AppFilterChip(
                        selected = currency == code,
                        onClick = { onCurrencyChange(code) },
                        label = "${code.symbol} ${code.storageKey}",
                        enabled = enabled,
                    )
                }
            }
            OutlinedTextField(
                value = originalAmountText,
                onValueChange = onOriginalAmountChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.expense_edit_original_amount_field_label, currency.storageKey)) },
                placeholder = { Text(if (currency.noFractionDigits) "1280" else "36.80") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                singleLine = true,
                enabled = enabled,
            )
            if (currency != FxContract.HomeCurrency) {
                Text(
                    text = stringResource(R.string.expense_edit_fx_hint),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
internal fun ExpenseEditMerchantField(
    merchant: String,
    onMerchantChange: (String) -> Unit,
    enabled: Boolean = true,
) {
    OutlinedTextField(
        value = merchant,
        onValueChange = onMerchantChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(stringResource(R.string.expense_edit_merchant_field_label)) },
        singleLine = true,
        enabled = enabled,
    )
}

@Composable
internal fun ExpenseEditCategoryField(
    category: String,
    categories: List<String>,
    onCategoryChange: (String) -> Unit,
    enabled: Boolean = true,
) {
    OutlinedTextField(
        value = category,
        onValueChange = onCategoryChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(stringResource(R.string.expense_edit_category_field_label)) },
        singleLine = true,
        enabled = enabled,
    )
    if (categories.isNotEmpty()) {
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(categories, key = { it }) { item ->
                SelectableCategoryChip(
                    selected = category == item,
                    label = item,
                    enabled = enabled,
                    onClick = { onCategoryChange(item) },
                )
            }
        }
    }
}

@Composable
internal fun ExpenseEditNoteField(
    note: String,
    onNoteChange: (String) -> Unit,
    enabled: Boolean = true,
) {
    OutlinedTextField(
        value = note,
        onValueChange = onNoteChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(stringResource(R.string.expense_edit_note_field_label)) },
        enabled = enabled,
    )
}

@Composable
internal fun ExpenseEditSourceInfo(
    source: String,
    confidence: Double?,
) {
    Text(
        stringResource(R.string.expense_edit_source_label, source),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    confidence?.let {
        Text(
            stringResource(R.string.expense_edit_confidence_label, (it * 100).toInt()),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
