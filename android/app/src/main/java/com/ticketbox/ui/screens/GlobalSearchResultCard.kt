package com.ticketbox.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.GlobalSearchResultKind
import com.ticketbox.viewmodel.GlobalSearchResultUi

/** One global-search hit: pending/confirmed badge, merchant + meta line, the
 *  amount, and a "命中：<field>" line naming what matched (merchant / amount /
 *  …). Tap opens the expense. Extracted from GlobalSearchScreen to keep that
 *  file's controls + states under the per-file line budget. */
@Composable
internal fun SearchResultCard(
    result: GlobalSearchResultUi,
    onClick: () -> Unit,
) {
    val expense = result.expense
    AppContentCard(
        modifier = Modifier.clickable(onClick = onClick),
        contentPadding = PaddingValues(AppSpacing.cardPaddingSmall),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.Top,
        ) {
            SearchKindBadge(kind = result.kind)
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = result.title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTypography.cardTitle.weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = "${expense.category} · ${expense.source} · ${displayTime(expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt)}",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                text = formatAmount(expense.amountCents),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleMedium.tabularNum(),
                fontWeight = AppTypography.amountMedium.weight,
                maxLines = 1,
            )
        }
        Text(
            text = stringResource(R.string.global_search_result_matched, result.matchedField.asString()),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun SearchKindBadge(kind: GlobalSearchResultKind) {
    val states = LocalStateTokens.current
    val tone = when (kind) {
        GlobalSearchResultKind.Pending -> states.info
        GlobalSearchResultKind.Confirmed -> states.success
    }
    val label = when (kind) {
        GlobalSearchResultKind.Pending -> stringResource(R.string.global_search_badge_pending)
        GlobalSearchResultKind.Confirmed -> stringResource(R.string.global_search_badge_confirmed)
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(tone.bg)
            .border(BorderStroke(1.dp, tone.border), RoundedCornerShape(AppRadius.pill))
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.miniGap),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            color = tone.fg,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = AppTypography.chip.weight,
            maxLines = 1,
        )
    }
}
