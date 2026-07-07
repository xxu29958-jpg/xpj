package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.FxContract
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppFilterChipOptions
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun ExpenseCurrencySelector(
    currency: CurrencyCode,
    enabled: Boolean,
    onCurrencySelect: (CurrencyCode) -> Unit,
) {
    var expanded by rememberSaveable { mutableStateOf(currency != FxContract.HomeCurrency) }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        CurrencySummaryRow(
            currency = currency,
            expanded = expanded,
            enabled = enabled,
            onToggle = { expanded = !expanded },
        )
        if (expanded) {
            ExpenseCurrencyChoices(
                currency = currency,
                enabled = enabled,
                onCurrencySelect = onCurrencySelect,
            )
        }
    }
}

@Composable
private fun CurrencySummaryRow(
    currency: CurrencyCode,
    expanded: Boolean,
    enabled: Boolean,
    onToggle: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = stringResource(R.string.expense_edit_currency_label),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = AppTextHierarchy.caption.weight,
            )
            Text(
                text = stringResource(R.string.expense_edit_currency_value, currency.symbol, currency.storageKey),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = AppTextHierarchy.body.weight,
            )
        }
        QuietOutlinedButton(
            text = if (expanded) {
                stringResource(R.string.expense_edit_currency_collapse_button)
            } else {
                stringResource(R.string.expense_edit_currency_change_button)
            },
            enabled = enabled,
            onClick = onToggle,
        )
    }
}

@Composable
private fun ExpenseCurrencyChoices(
    currency: CurrencyCode,
    enabled: Boolean,
    onCurrencySelect: (CurrencyCode) -> Unit,
) {
    AppCompactChips {
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            CurrencyCode.entries.forEach { code ->
                ExpenseCurrencyChoice(
                    code = code,
                    selected = currency == code,
                    enabled = enabled,
                    onClick = { onCurrencySelect(code) },
                )
            }
        }
    }
}

@Composable
private fun ExpenseCurrencyChoice(
    code: CurrencyCode,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    AppFilterChip(
        label = code.storageKey,
        selected = selected,
        onClick = onClick,
        options = AppFilterChipOptions(enabled = enabled),
    )
}
