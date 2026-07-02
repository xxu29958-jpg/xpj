package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppProgressBar
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import kotlin.math.roundToInt

private fun debtRowStatusRank(status: String): Int = when (status) {
    DebtLinkStatuses.OPEN -> 0
    DebtLinkStatuses.CLEARED -> 1
    else -> 2
}

private fun isCommunalRow(debt: Debt): Boolean {
    val foreign = debt.originalCurrencyCode != null && debt.originalCurrencyCode != debt.homeCurrencyCode
    return debt.isMember && !foreign
}

internal fun groupDebtsForList(debts: List<Debt>): Pair<List<Debt>, List<Debt>> {
    val (members, externals) = debts.partition { isCommunalRow(it) }
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
internal fun MemberDebtRow(
    debt: Debt,
    onClick: (() -> Unit)? = null,
    showDivider: Boolean = true,
) {
    val name = debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
    val ratio = communalRatio(debt.paidAmountCents, debt.principalAmountCents)

    AppListRow(
        modifier = Modifier.fillMaxWidth(),
        onClick = onClick,
        settled = !debt.isOpen,
        showDivider = showDivider,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                name,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(
                    memberDebtHeadlineRes(
                        debt.viewerIsDebtor,
                        debt.status,
                        isForgiven = debt.isForgiven,
                        ratio = ratio,
                    ),
                ),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (debt.isOpen) {
                Spacer(Modifier.size(AppSpacing.compactGap))
                val percent = (ratio.coerceIn(0f, 1f) * 100).roundToInt()
                AppProgressBar(
                    fraction = ratio,
                    tone = LocalStateTokens.current.success,
                    height = AppSpacing.miniGap,
                    contentDescription = stringResource(R.string.debt_member_progress_a11y, percent),
                )
            }
        }
        Spacer(Modifier.width(AppSpacing.smallGap))
        DebtStatusBadge(
            text = stringResource(memberDebtStatusLabelRes(debt.status)),
            tone = memberDebtStatusTone(debt.status),
        )
    }
}
