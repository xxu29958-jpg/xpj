package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.FxContract
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun ExpenseCurrencySelector(
    currency: CurrencyCode,
    enabled: Boolean,
    onCurrencySelect: (CurrencyCode) -> Unit,
) {
    var expanded by rememberSaveable { mutableStateOf(currency != FxContract.HomeCurrency) }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
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
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(
                text = stringResource(R.string.expense_edit_currency_label),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
            )
            Text(
                text = "${currency.symbol} ${currency.storageKey}",
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
        }
        AppSecondaryButton(
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
    LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        items(CurrencyCode.entries, key = { it.storageKey }) { code ->
            ExpenseCurrencyChoice(
                code = code,
                selected = currency == code,
                enabled = enabled,
                onClick = { onCurrencySelect(code) },
            )
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
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.extraSmall)
    val borderColor = if (selected) {
        visuals.primary.copy(alpha = AppAlpha.medium)
    } else {
        MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle)
    }
    val backgroundColor = if (selected) {
        visuals.brandPrimaryBg.copy(alpha = AppAlpha.opaque)
    } else {
        Color.Transparent
    }
    Text(
        text = "${code.symbol} ${code.storageKey}",
        modifier = Modifier
            .clip(shape)
            .background(backgroundColor)
            .border(width = 1.dp, color = borderColor, shape = shape)
            .selectable(selected = selected, enabled = enabled, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.miniGap),
        color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = if (selected) AppTextHierarchy.heading.weight else FontWeight.Medium,
    )
}
