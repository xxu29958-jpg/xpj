package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
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
import com.ticketbox.domain.model.CurrencyCode

@Composable
internal fun CurrencyChoiceField(currency: CurrencyCode?, enabled: Boolean = true,
    title: String = stringResource(R.string.currency_picker_title), onChoose: (CurrencyCode) -> Unit) {
    var choosing by rememberSaveable { mutableStateOf(false) }
    AppSecondaryButton(text = currency?.let { "${it.storageKey} · ${it.displayName}" }
        ?: title, enabled = enabled, onClick = { choosing = true })
    if (choosing && enabled) CurrencyPickerDialog(currency, title = title, onChoose = { onChoose(it); choosing = false },
        onDismiss = { choosing = false })
}

@Composable
internal fun CurrencyPickerDialog(selected: CurrencyCode? = null,
    title: String = stringResource(R.string.currency_picker_title), onChoose: (CurrencyCode) -> Unit, onDismiss: () -> Unit) {
    var query by rememberSaveable { mutableStateOf("") }
    val choices = CurrencyCode.entries.filter { it.storageKey.contains(query.trim(), ignoreCase = true) || it.displayName.contains(query.trim()) }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(title) },
        text = { Column {
            OutlinedTextField(value = query, onValueChange = { query = it }, singleLine = true,
                label = { Text(stringResource(R.string.currency_picker_search)) }, modifier = Modifier.fillMaxWidth())
            LazyColumn(Modifier.heightIn(max = 360.dp)) {
                items(choices, key = { it.storageKey }) { currency ->
                    TextButton(onClick = { onChoose(currency) }, modifier = Modifier.fillMaxWidth()) {
                        Text("${currency.storageKey} · ${currency.displayName}" + if (currency == selected) " ✓" else "",
                            modifier = Modifier.fillMaxWidth(), color = MaterialTheme.colorScheme.onSurface)
                    }
                }
                if (choices.isEmpty()) item { Text(stringResource(R.string.currency_picker_empty)) }
            }
        } }, confirmButton = {}, dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        })
}
