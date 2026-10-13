package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum

/** One projection for member and external facts; their commands keep their existing owners. */
@Composable
internal fun DebtSummaryCard(debt: Debt) {
    val recordDisplay = CurrencyDisplay.forRecord(debt.homeCurrencyCode)
    val visuals = LocalThemeVisuals.current
    val unknown = stringResource(R.string.debt_detail_component_unknown)
    val time = debt.accountingTime
    val occurrence = time?.userLocalDate ?: stringResource(R.string.accounting_time_date_unknown)
    val principalDate = if (time?.accountingDate != null && time.accountingDate != time.userLocalDate) {
        stringResource(R.string.accounting_time_date_with_ledger_day, occurrence, time.accountingDate)
    } else occurrence
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        DebtRemainingCard(debt)
        Column {
            DebtBalanceFact(stringResource(R.string.debt_detail_principal),
                formatDisplayAmount(debt.principalAmountCents, recordDisplay), R.drawable.ic_lucide_receipt_text,
                subtitle = principalDate)
            DebtBalanceFact(stringResource(R.string.debt_detail_paid),
                formatDisplayAmount(debt.paidAmountCents, recordDisplay), R.drawable.ic_lucide_check)
            DebtBalanceFact(stringResource(R.string.debt_detail_forgiven),
                debt.forgivenAmountCents?.let { formatDisplayAmount(it, recordDisplay) } ?: unknown,
                R.drawable.ic_lucide_heart_handshake, visuals.surfaceApricot)
            DebtBalanceFact(stringResource(R.string.debt_detail_adjustment),
                debt.adjustmentAmountCents?.let { (if (it > 0) "+" else "") + formatDisplayAmount(it, recordDisplay) } ?: unknown,
                R.drawable.ic_lucide_sliders_horizontal, visuals.surfaceLilac)
        }
        Text(stringResource(R.string.debt_detail_component_hint), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        debt.originalCurrencyCode?.takeIf { it != debt.homeCurrencyCode }?.let { code ->
            debt.originalAmountMinor?.let { amount ->
                DebtSummaryRow(stringResource(R.string.debt_detail_original_currency, code),
                    formatDisplayAmount(amount, CurrencyDisplay.forRecord(code)))
            }
        }
        debt.note?.takeIf { it.isNotBlank() }?.let { note ->
            HorizontalDivider()
            Text(
                stringResource(R.string.debt_context_title),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(note, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable
private fun DebtRemainingCard(debt: Debt) {
    AppPaperCard {
        Column(Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Text(stringResource(R.string.debt_detail_remaining_currency, debt.homeCurrencyCode),
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            AppAmountText(formatDisplayAmount(debt.remainingAmountCents, CurrencyDisplay.forRecord(debt.homeCurrencyCode)),
                modifier = Modifier.fillMaxWidth(), role = AppAmountRole.Hero)
            DebtStatusBadge(
                text = stringResource(if (debt.isMember) memberDebtStatusLabelRes(debt.status)
                    else debtLinkStatusLabelRes(debt.status)),
                tone = if (debt.isMember) memberDebtStatusTone(debt.status) else debtLinkStatusTone(debt.status),
            )
            if (debt.isMember) Text(
                if (debt.isCleared && debt.sourceType in setOf("bill_split", "bill_split_return"))
                    stringResource(R.string.split_agreement_leg_cleared)
                else stringResource(memberDebtHeadlineRes(debt.viewerIsDebtor, debt.status, debt.isForgiven,
                    communalRatio(debt.paidAmountCents, debt.principalAmountCents))),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun DebtBalanceFact(label: String, value: String, icon: Int,
    background: Color = LocalThemeVisuals.current.brandPrimaryBg, subtitle: String? = null) {
    AppAdaptiveContentActionRow(modifier = Modifier.padding(vertical = AppSpacing.compactGap),
        style = AppAdaptiveContentActionStyle(compactAction = true),
        content = {
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                verticalAlignment = Alignment.CenterVertically) {
                SettingsEntryIcon(ImageVector.vectorResource(icon), background = background)
                Column {
                    Text(label, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                    subtitle?.let { Text(it, style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
            }
        },
        action = { modifier -> Text(value, modifier = modifier,
            style = MaterialTheme.typography.bodyMedium.tabularNum(), fontWeight = FontWeight.SemiBold) })
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}

// Activity records use the same adaptive label/value treatment without decorative fact icons.
@Composable
internal fun DebtSummaryRow(label: String, value: String) {
    AppAdaptiveContentActionRow(
        style = AppAdaptiveContentActionStyle(compactAction = true),
        content = { Text(label, style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant) },
        action = { modifier -> Text(value, modifier = modifier,
            style = MaterialTheme.typography.bodyMedium.tabularNum(), fontWeight = FontWeight.Medium) },
    )
}

/** A projection of the entered amount; a member proposal changes no fact until confirmation. */
@Composable
internal fun DebtRepaymentBalancePreview(debt: Debt, input: String) {
    val currency = CurrencyDisplay.forRecord(debt.homeCurrencyCode)
    val amount = CurrencyCode.fromStorageKeyOrNull(debt.homeCurrencyCode)?.let { parseAmountCents(input, it) }
    val remaining = amount?.takeIf { it > 0 && it <= debt.remainingAmountCents }?.let { debt.remainingAmountCents - it }
    AppPaperCard {
        Column(Modifier.fillMaxWidth().padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Text(stringResource(R.string.debt_payment_balance_preview), style = MaterialTheme.typography.titleMedium)
            AppAdaptiveContentActionRow(style = AppAdaptiveContentActionStyle(compactAction = true, wideActionWeight = 1f), content = {
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                    Text(stringResource(R.string.debt_payment_balance_before), style = MaterialTheme.typography.bodySmall)
                    AppAmountText(formatDisplayAmount(debt.remainingAmountCents, currency))
                }
            }, action = { modifier ->
                AppPaperCard(modifier = modifier, containerColor = LocalThemeVisuals.current.brandPrimaryBg) {
                    Column(Modifier.padding(AppSpacing.contentGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                        Text(stringResource(R.string.debt_payment_balance_after), style = MaterialTheme.typography.bodySmall)
                        AppAmountText(remaining?.let { formatDisplayAmount(it, currency) }
                            ?: stringResource(R.string.debt_detail_component_unknown))
                    }
                }
            })
            if (amount != null && amount > debt.remainingAmountCents) Text(stringResource(R.string.debt_payment_over_remaining),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
    }
}
