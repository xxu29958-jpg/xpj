package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

/** Member direction is the server's participant projection, never the storage-side direction. */
internal fun debtViewDirection(debt: Debt): String? = if (debt.isMember) {
    when (debt.viewerIsDebtor) {
        true -> DebtDirections.I_OWE
        false -> DebtDirections.OWED_TO_ME
        null -> null
    }
} else debt.direction

internal data class DebtListTotal(val direction: String, val currency: String, val count: Int, val amount: Long?)

/** Both readers provide a complete, identity-scoped list, including retained offline rows. */
internal fun debtListTotals(debts: List<Debt>): List<DebtListTotal> = debts
    .filter { it.isOpen && debtViewDirection(it) != null }
    .groupBy { requireNotNull(debtViewDirection(it)) to it.homeCurrencyCode }
    .map { (key, rows) ->
        val amount = try {
            rows.fold(0L) { total, debt -> Math.addExact(total, debt.remainingAmountCents) }
        } catch (_: ArithmeticException) {
            null // Keep the rows readable; an overflowing projection must not become a false balance.
        }
        DebtListTotal(key.first, key.second, rows.size, amount)
    }

@Composable
internal fun DebtListTotalCard(total: DebtListTotal) {
    val payable = total.direction == DebtDirections.I_OWE
    val visuals = LocalThemeVisuals.current
    AppPaperCard(containerColor = if (payable) visuals.surfaceApricot else visuals.brandPrimaryBg) {
        Column(Modifier.padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(stringResource(if (payable) R.string.debt_list_total_payable else R.string.debt_list_total_receivable,
                total.currency), style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (total.amount == null) {
                Text(stringResource(R.string.debt_list_total_out_of_range), style = MaterialTheme.typography.bodyMedium)
            } else {
                AppAmountText(formatDisplayAmount(total.amount, CurrencyDisplay.forRecord(total.currency)), role = AppAmountRole.Hero)
            }
            Text(stringResource(R.string.debt_list_total_count, total.count), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
