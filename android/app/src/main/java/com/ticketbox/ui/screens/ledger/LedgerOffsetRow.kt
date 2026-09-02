@file:OptIn(ExperimentalFoundationApi::class)

package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.StreamOffset
import com.ticketbox.domain.model.StreamOffsetKind
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppDensity
import com.ticketbox.ui.design.AppListDensity
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalStateTokens

/**
 * Root-row lineage state chip (部分退回 / 已退回 / 已冲销) — the server-owned
 * net state of the bill, same copy as the Web lineage chip. Confirmed renders
 * nothing. Refund states use the success tone (money came back), reversal the
 * neutral tone (the bill simply no longer counts) — never a warning, this is
 * a fact state, not an alarm.
 */
@Composable
internal fun LedgerLineageChip(status: ExpenseLineageStatus, modifier: Modifier = Modifier) {
    if (!status.chipVisible) return
    val tone = when (status) {
        ExpenseLineageStatus.PartiallyRefunded, ExpenseLineageStatus.FullyRefunded ->
            LocalStateTokens.current.success
        ExpenseLineageStatus.Reversed, ExpenseLineageStatus.Confirmed ->
            LocalStateTokens.current.neutral
    }
    val label = stringResource(
        when (status) {
            ExpenseLineageStatus.PartiallyRefunded -> R.string.ledger_lineage_partially_refunded
            ExpenseLineageStatus.FullyRefunded -> R.string.ledger_lineage_fully_refunded
            ExpenseLineageStatus.Reversed -> R.string.ledger_lineage_reversed
            ExpenseLineageStatus.Confirmed -> R.string.ledger_lineage_partially_refunded
        },
    )
    Text(
        text = label,
        modifier = modifier
            .clip(CircleShape)
            .background(tone.bg)
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap),
        color = tone.fg,
        style = MaterialTheme.typography.labelSmall,
        fontWeight = AppTypography.chip.weight,
        maxLines = 1,
    )
}

internal data class LedgerOffsetItemState(
    val item: ConfirmedStreamItem.OffsetRow,
)

/**
 * Offset event row (退款 / 拒付 / 冲销) — one compact event row in EVERY view
 * mode: an event never masquerades as an expense card. No checkbox and no
 * selection long-press (offsets are never batch targets); a tap opens the
 * root fact detail. Refund/chargeback carry a signed inflow money slot in the
 * ORIGINAL currency (+$5.00; the home-currency equivalent lives in the fact
 * detail); a reversal is a money-less event row.
 */
@Composable
internal fun LedgerOffsetRow(
    state: LedgerOffsetItemState,
    onOpen: () -> Unit,
) {
    val item = state.item
    val offset = item.offset
    val rowMetrics = AppDensity.rowMetrics(AppListDensity.Compact)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onOpen),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = AppSpacing.miniGap, vertical = rowMetrics.rowPadding),
            horizontalArrangement = Arrangement.spacedBy(rowMetrics.itemSpacing),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            LedgerOffsetKindChip(kind = offset.kind)
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = item.root.merchant?.takeIf { it.isNotBlank() }
                        ?: stringResource(R.string.ledger_item_merchant_empty),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = AppTextHierarchy.body.weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = offset.category,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (offset.kind.isMoneyEvent) {
                LedgerOffsetInflowAmount(offset = offset)
            }
        }
        HorizontalDivider(
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium),
        )
    }
}

@Composable
private fun LedgerOffsetKindChip(kind: StreamOffsetKind) {
    val tone = when (kind) {
        StreamOffsetKind.Refund, StreamOffsetKind.Chargeback -> LocalStateTokens.current.success
        StreamOffsetKind.Reversal -> LocalStateTokens.current.neutral
    }
    val label = stringResource(
        when (kind) {
            StreamOffsetKind.Refund -> R.string.ledger_offset_kind_refund
            StreamOffsetKind.Chargeback -> R.string.ledger_offset_kind_chargeback
            StreamOffsetKind.Reversal -> R.string.ledger_offset_kind_reversal
        },
    )
    Text(
        text = label,
        modifier = Modifier
            .clip(CircleShape)
            .background(tone.bg)
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap),
        color = tone.fg,
        style = MaterialTheme.typography.labelSmall,
        fontWeight = AppTypography.chip.weight,
        maxLines = 1,
    )
}

@Composable
private fun LedgerOffsetInflowAmount(offset: StreamOffset, modifier: Modifier = Modifier) {
    val text = stringResource(
        R.string.ledger_offset_inflow_amount,
        formatDisplayAmount(
            offset.originalAmountMinor,
            CurrencyDisplay.forRecord(offset.originalCurrencyCode),
        ),
    )
    Box(
        modifier = modifier.widthIn(
            min = AppAdaptiveAmountRowDefaults.statusMinWidth,
            max = AppAdaptiveAmountRowDefaults.secondaryMetaInlineMaxWidth,
        ),
        contentAlignment = Alignment.CenterEnd,
    ) {
        AppEndAlignedAmountText(
            modifier = Modifier.fillMaxWidth(),
            text = text,
            role = AppAmountRole.Compact,
            color = LocalStateTokens.current.success.fg,
        )
    }
}
