package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.data.repository.ManualEntryTemplate
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.presentation.formatMinorAmountInput
import com.ticketbox.presentation.parseMinorAmount
import com.ticketbox.ui.screens.ManualCategoryChoices
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFields
import com.ticketbox.ui.screens.expense.ExpenseCurrencyFieldOptions
import java.util.UUID

@Composable
internal fun ManualTemplateEditor(
    original: ManualEntryTemplate?,
    homeCurrency: CurrencyCode,
    categories: List<String>,
    saving: Boolean,
    actions: ManualTemplateEditorActions,
) {
    val initialCurrency = CurrencyCode.fromStorageKeyOrNull(original?.currencyCode) ?: homeCurrency
    val id by rememberSaveable { mutableStateOf(original?.id ?: UUID.randomUUID().toString()) }
    var name by rememberSaveable { mutableStateOf(original?.name.orEmpty()) }
    var amount by rememberSaveable { mutableStateOf(formatMinorAmountInput(original?.amountMinor, initialCurrency)) }
    var currency by rememberSaveable { mutableStateOf(initialCurrency) }
    var category by rememberSaveable { mutableStateOf(original?.category.orEmpty()) }
    var note by rememberSaveable { mutableStateOf(original?.note.orEmpty()) }
    var invalid by rememberSaveable { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(stringResource(if (original == null) R.string.widget_template_add else R.string.widget_template_edit))
        OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), enabled = !saving,
            label = { Text(stringResource(R.string.widget_template_name)) }, singleLine = true)
        ExpenseCurrencyFields(currency, { currency = it }, amount, { amount = it },
            options = ExpenseCurrencyFieldOptions(enabled = !saving, autoFocusAmount = false, showFxHint = false))
        OutlinedTextField(category, { category = it }, Modifier.fillMaxWidth(), enabled = !saving,
            label = { Text(stringResource(R.string.widget_template_category)) }, singleLine = true)
        ManualCategoryChoices(categories = categories, selectedCategory = category, enabled = !saving,
            onCategoryChange = { category = it })
        OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth(), enabled = !saving,
            label = { Text(stringResource(R.string.widget_template_note)) })
        if (invalid) Text(stringResource(R.string.widget_template_invalid))
        Row {
            Button(enabled = !saving, onClick = {
                val minor = parseMinorAmount(amount, currency)
                invalid = name.isBlank() || category.isBlank() || minor == null || minor < 0
                if (!invalid) actions.onSave(ManualEntryTemplate(id, name.trim(), requireNotNull(minor), currency.storageKey, category.trim(), note))
            }) { Text(stringResource(R.string.widget_template_save)) }
            TextButton(onClick = actions.onCancel, enabled = !saving) { Text(stringResource(R.string.widget_cancel)) }
        }
        actions.onDelete?.let { TextButton(onClick = it, enabled = !saving) { Text(stringResource(R.string.widget_template_delete)) } }
    }
}

internal data class ManualTemplateEditorActions(
    val onSave: (ManualEntryTemplate) -> Unit, val onDelete: (() -> Unit)?, val onCancel: () -> Unit,
)
