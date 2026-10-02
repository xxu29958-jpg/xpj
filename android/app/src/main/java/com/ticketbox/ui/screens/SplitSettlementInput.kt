package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppFilterChipOptions
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.design.AppSpacing

private val settlementSign = Regex("^(\\s*)[+-]")
private val settlementLeadingSpace = Regex("^(\\s*)")

/** Direction is derived from the retained signed input, never a second saved value. */
@Composable
internal fun SplitSettlementInput(value: String, currency: String, enabled: Boolean, onValueChange: (String) -> Unit) {
    val returning = value.trimStart().startsWith("-")
    val amount = value.replaceFirst(settlementSign, "$1")
    Text(stringResource(R.string.split_agreement_settlement_direction), style = MaterialTheme.typography.labelLarge)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        AppFilterChip(stringResource(R.string.split_agreement_direction_pay), selected = !returning,
            onClick = { onValueChange(settlementWithDirection(value, false)) },
            options = AppFilterChipOptions(enabled = enabled))
        AppFilterChip(stringResource(R.string.split_agreement_direction_return), selected = returning,
            onClick = { onValueChange(settlementWithDirection(value, true)) },
            options = AppFilterChipOptions(enabled = enabled))
    }
    AppTextInput(AppTextInputState(stringResource(R.string.split_agreement_settlement_input, currency), amount,
        enabled = enabled, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)),
        AppTextInputActions(onValueChange = { entered ->
            onValueChange(if (settlementSign.containsMatchIn(entered)) entered else settlementWithDirection(entered, returning))
        }))
    Text(stringResource(R.string.split_agreement_settlement_help), style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant)
}

private fun settlementWithDirection(value: String, returning: Boolean): String =
    value.replaceFirst(settlementSign, "$1").replaceFirst(settlementLeadingSpace, if (returning) "$1-" else "$1")
