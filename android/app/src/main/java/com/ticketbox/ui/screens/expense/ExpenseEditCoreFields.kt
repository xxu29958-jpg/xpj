package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.annotation.StringRes
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.domain.model.FxContract
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.LocalAppImeVisible
import com.ticketbox.ui.design.AppSpacing

@Immutable
internal data class ExpenseCurrencyFieldOptions(
    val enabled: Boolean = true,
    val autoFocusAmount: Boolean = true,
    val onAmountFocusChanged: (Boolean) -> Unit = {},
)

@Composable
internal fun ExpenseCurrencyFields(
    currency: CurrencyCode,
    onCurrencyChange: (CurrencyCode) -> Unit,
    originalAmountText: String,
    onOriginalAmountChange: (String) -> Unit,
    options: ExpenseCurrencyFieldOptions = ExpenseCurrencyFieldOptions(),
) {
    // The manual-entry sheet can opt into immediate amount entry, while existing
    // receipt edit pages keep the page readable until the user taps a field.
    // The `enabled` flag still gates read-only pages so they never steal focus.
    val amountFocus = remember { FocusRequester() }
    val keyboardVisible = LocalAppImeVisible.current
    LaunchedEffect(options.enabled, options.autoFocusAmount) {
        if (options.enabled && options.autoFocusAmount) amountFocus.requestFocus()
    }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(
            if (keyboardVisible) AppSpacing.miniGap else AppSpacing.smallGap,
        ),
    ) {
        Text(stringResource(R.string.expense_edit_currency_card_title), style = MaterialTheme.typography.titleSmall)
        OutlinedTextField(
            value = originalAmountText,
            onValueChange = onOriginalAmountChange,
            modifier = Modifier
                .fillMaxWidth()
                .focusRequester(amountFocus)
                .onFocusChanged { options.onAmountFocusChanged(it.isFocused) },
            label = { Text(stringResource(R.string.expense_edit_original_amount_field_label)) },
            placeholder = {
                Text(
                    stringResource(
                        if (currency.noFractionDigits) {
                            R.string.expense_edit_original_amount_placeholder_no_fraction
                        } else {
                            R.string.expense_edit_original_amount_placeholder_fraction
                        },
                    ),
                )
            },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            singleLine = true,
            enabled = options.enabled,
        )
        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            items(CurrencyCode.entries, key = { it.storageKey }) { code ->
                AppFilterChip(
                    selected = currency == code,
                    onClick = { onCurrencyChange(code) },
                    label = "${code.symbol} ${code.storageKey}",
                    enabled = options.enabled,
                )
            }
        }
        if (currency != FxContract.HomeCurrency) {
            Text(
                text = stringResource(R.string.expense_edit_fx_hint),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
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
        LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
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
    val labelRes = expenseSourceLabelRes(source)
    val display = labelRes?.let { stringResource(it) } ?: source
    Text(
        stringResource(R.string.expense_edit_source_label, display),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    confidence?.let {
        Text(
            stringResource(R.string.expense_edit_confidence_label, (it * 100).toInt()),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** ``Expense.source`` 存储值（见 [ExpenseSourceValues]）映射到人话显示标签，
 *  三端词汇同步。未知来源返回 ``null``，由调用方回退到原始 token。纯函数，可单测。 */
@StringRes
internal fun expenseSourceLabelRes(source: String): Int? {
    if (source.startsWith(ExpenseSourceValues.NOTIFICATION_DRAFT_PREFIX)) {
        return R.string.expense_edit_source_notification
    }
    return when (source) {
        ExpenseSourceValues.IPHONE_SCREENSHOT -> R.string.expense_edit_source_iphone
        ExpenseSourceValues.ANDROID_SCREENSHOT -> R.string.expense_edit_source_android
        ExpenseSourceValues.MANUAL_ENTRY -> R.string.expense_edit_source_manual
        ExpenseSourceValues.CSV_IMPORT -> R.string.expense_edit_source_csv
        ExpenseSourceValues.BILL_SPLIT_RECEIVED -> R.string.expense_edit_source_bill_split
        else -> null
    }
}
