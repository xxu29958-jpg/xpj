package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

private fun debtRowStatusRank(status: String): Int = when (status) {
    DebtLinkStatuses.OPEN -> 0
    DebtLinkStatuses.CLEARED -> 1
    else -> 2
}

internal fun groupDebtsForList(debts: List<Debt>): Pair<List<Debt>, List<Debt>> {
    val (members, externals) = debts.partition { it.isMember }
    return members.sortedBy { debtRowStatusRank(it.status) } to externals.sortedBy { debtRowStatusRank(it.status) }
}

@Composable
internal fun DebtSectionHeader(title: String) {
    Text(
        title,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = AppSpacing.smallGap, bottom = AppSpacing.miniGap),
    )
}

@Composable
internal fun DebtListRow(
    debt: Debt,
    onClick: (() -> Unit)? = null,
    showDivider: Boolean = true,
) {
    val display = CurrencyDisplay.forRecord(debt.homeCurrencyCode)
    val visuals = LocalThemeVisuals.current

    AppListRow(
        modifier = Modifier.fillMaxWidth(),
        onClick = onClick,
        settled = !debt.isOpen,
        showDivider = showDivider,
    ) {
        SettingsEntryIcon(ImageVector.vectorResource(R.drawable.ic_lucide_user_round),
            background = if (debt.isMember) visuals.brandPrimaryBg else visuals.surfaceLilac)
        Spacer(Modifier.width(AppSpacing.contentGap))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppAdaptiveEditAmountRow(
                amount = formatDisplayAmount(debt.remainingAmountCents, display),
                style = AppAdaptiveAmountRowStyle(trailingWeight = AppAdaptiveAmountRowDefaults.listTrailingWeight),
            ) {
                Text(debtDetailTitle(debt), style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold)
            }
            Text(stringResource(R.string.debt_list_card_balance,
                debt.homeCurrencyCode, formatDisplayAmount(debt.principalAmountCents, display)),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                DebtStatusBadge(
                    text = stringResource(if (debt.isMember) memberDebtStatusLabelRes(debt.status)
                        else debtLinkStatusLabelRes(debt.status)),
                    tone = if (debt.isMember) memberDebtStatusTone(debt.status) else debtLinkStatusTone(debt.status),
                )
                if (debt.originalCurrencyCode != null && debt.originalCurrencyCode != debt.homeCurrencyCode &&
                    debt.originalAmountMinor != null) {
                    Text(stringResource(R.string.debt_list_card_original,
                        debt.originalCurrencyCode, formatDisplayAmount(debt.originalAmountMinor,
                            CurrencyDisplay.forRecord(debt.originalCurrencyCode))),
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}
