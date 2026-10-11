package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.expenseSourceLabelRes
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.viewmodel.GlobalSearchResultKind
import com.ticketbox.viewmodel.GlobalSearchResultUi

/** Search keeps its query owner and destination; hits use the common reading row. */
@Composable
internal fun SearchResultCard(result: GlobalSearchResultUi, onClick: () -> Unit) {
    val expense = result.expense
    val sourceLabel = expenseSourceLabelRes(expense.source)?.let { stringResource(it) } ?: expense.source
    AppListRow(onClick = onClick) {
        SettingsEntryIcon(ImageVector.vectorResource(R.drawable.ic_lucide_receipt_text))
        Spacer(Modifier.width(AppSpacing.contentGap))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppAdaptiveEditAmountRow(
                amount = formatDisplayAmount(expense.amountCents,
                    CurrencyDisplay.forRecord(expense.homeCurrencyCode ?: expense.homeCurrency.storageKey)),
                style = AppAdaptiveAmountRowStyle(trailingWeight = AppAdaptiveAmountRowDefaults.listTrailingWeight),
            ) {
                Text(result.title, style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTypography.cardTitle.weight)
            }
            Text(stringResource(R.string.global_search_result_meta, expense.category, sourceLabel,
                com.ticketbox.ui.components.expenseClockLabel(expense).asString()),
                color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                SearchKindBadge(result.kind)
                Text(stringResource(R.string.global_search_result_matched, result.matchedField.asString()),
                    color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

@Composable
private fun SearchKindBadge(kind: GlobalSearchResultKind) {
    val states = LocalStateTokens.current
    StatusPill(
        text = stringResource(if (kind == GlobalSearchResultKind.Pending)
            R.string.global_search_badge_pending else R.string.global_search_badge_confirmed),
        tone = if (kind == GlobalSearchResultKind.Pending) states.info else states.success,
    )
}
