package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.ui.components.AppAdaptiveMetricGrid
import com.ticketbox.ui.components.AppAdaptiveMetricGridCompactMinWidth
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing

/** Server-owned amounts below the original spend; the shared metric grid handles large type. */
@Composable
internal fun FactOffsetSummary(amounts: FactAmountLabels) {
    val refunded = amounts.refunded ?: return
    val net = amounts.net ?: return
    val metrics = listOf(R.string.expense_offset_summary_refunded to refunded,
        R.string.expense_offset_summary_net to net)
    AppAdaptiveMetricGrid(itemCount = metrics.size, twoColumnMinWidth = AppAdaptiveMetricGridCompactMinWidth) { index, modifier ->
        val (label, value) = metrics[index]
        Column(modifier, verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(stringResource(label), color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium)
            AppAmountText(value)
        }
    }
}

@Composable
internal fun FactOffsetFxDifference(bundle: ExpenseFactBundle, homeDisplay: CurrencyDisplay) {
    val fxDifference = bundle.financialSummary.fxDifferenceCents
    if (fxDifference == 0L) return
    Text(
        text = stringResource(
            R.string.expense_offset_summary_fx_difference,
            formatDisplayAmount(fxDifference, homeDisplay),
        ),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
}
