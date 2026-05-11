package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

@Composable
internal fun ExpenseEditAmountField(
    amountText: String,
    onAmountChange: (String) -> Unit,
) {
    OutlinedTextField(
        value = amountText,
        onValueChange = onAmountChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text("金额，单位元") },
        placeholder = { Text("36.80") },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        singleLine = true,
    )
}

@Composable
internal fun ExpenseEditMerchantField(
    merchant: String,
    onMerchantChange: (String) -> Unit,
) {
    OutlinedTextField(
        value = merchant,
        onValueChange = onMerchantChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text("商家") },
        singleLine = true,
    )
}

@Composable
internal fun ExpenseEditCategoryField(
    category: String,
    categories: List<String>,
    onCategoryChange: (String) -> Unit,
) {
    OutlinedTextField(
        value = category,
        onValueChange = onCategoryChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text("分类") },
        singleLine = true,
    )
    if (categories.isNotEmpty()) {
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(categories, key = { it }) { item ->
                SelectableCategoryChip(
                    selected = category == item,
                    label = item,
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
) {
    OutlinedTextField(
        value = note,
        onValueChange = onNoteChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text("备注") },
    )
}

@Composable
internal fun ExpenseEditSourceInfo(
    source: String,
    confidence: Double?,
) {
    Text("来源：$source", color = MaterialTheme.colorScheme.onSurfaceVariant)
    confidence?.let {
        Text("识别置信度：${(it * 100).toInt()}%", color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
