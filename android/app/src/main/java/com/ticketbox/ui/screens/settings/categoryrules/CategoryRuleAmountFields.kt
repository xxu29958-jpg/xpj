package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.screens.settings.SettingsDialogTextInput
import com.ticketbox.ui.screens.settings.SettingsTextInputState

@Composable
internal fun CategoryRuleAmountFields(form: CategoryRuleDraftForm, busy: Boolean, onChange: (CategoryRuleDraftForm) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        TextButton(enabled = !busy && form.editingRule?.homeCurrencyCode == null && !form.hasUnconfirmedOriginalAmount,
            onClick = { expanded = true }) {
            Text(form.homeCurrencyCode ?: stringResource(R.string.category_rule_currency_choose))
        }
        DropdownMenu(expanded, onDismissRequest = { expanded = false }) {
            CurrencyCode.entries.forEach { currency ->
                DropdownMenuItem(text = { Text("${currency.storageKey} · ${currency.displayName}") }, onClick = {
                    expanded = false
                    onChange(form.copy(homeCurrencyCode = currency.storageKey, localMessage = null))
                })
            }
        }
    }
    SettingsDialogTextInput(SettingsTextInputState(label = stringResource(R.string.category_rule_amount_min),
        value = form.minimumAmount, enabled = !busy && !form.hasUnconfirmedOriginalAmount,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)),
        onValueChange = { onChange(form.copy(minimumAmount = it, localMessage = null)) })
    SettingsDialogTextInput(SettingsTextInputState(label = stringResource(R.string.category_rule_amount_max),
        value = form.maximumAmount, enabled = !busy && !form.hasUnconfirmedOriginalAmount,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)),
        onValueChange = { onChange(form.copy(maximumAmount = it, localMessage = null)) })
    Text(stringResource(if (form.hasUnconfirmedOriginalAmount) R.string.category_rule_currency_review else R.string.category_rule_amount_optional))
}
