package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.presentation.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing

/** The same recorded-currency display is used by the page and each day header. */
@Composable
internal fun LedgerAmounts(
    amounts: Map<String?, Long?>,
    role: AppAmountRole,
    modifier: Modifier = Modifier,
    endAligned: Boolean = false,
) {
    if (amounts.isEmpty()) {
        // Nothing recorded is not an amount: a quiet line rather than the amount type.
        Text(
            text = stringResource(R.string.ledger_total_empty),
            modifier = modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.titleMedium,
            textAlign = if (endAligned) TextAlign.End else TextAlign.Start,
        )
        return
    }
    val lines = amounts.map { (code, amount) -> ledgerRecordedAmountText(code, amount) }
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        lines.forEach { text ->
            if (endAligned) AppEndAlignedAmountText(text = text, role = role, modifier = Modifier.fillMaxWidth())
            else AppAmountText(text = text, role = role, modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun ledgerRecordedAmountText(code: String?, amount: Long?): String {
    if (code.isNullOrBlank()) return stringResource(R.string.ledger_total_unknown_currency)
    if (amount == null) return stringResource(R.string.ledger_total_unavailable, code)
    val formatted = formatDisplayAmount(amount, CurrencyDisplay.forRecord(code))
    return if (CurrencyCode.fromStorageKeyOrNull(code) != null) "$code $formatted" else formatted
}
