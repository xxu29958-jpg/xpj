package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing

/**
 * 「退回与冲销」金额分解表（原始/已退回/净额 + 汇差）。W2-B 起仅在 hero
 * 未表达净额时渲染（bundle 未知或 Confirmed 之外的展示兜底）；hero 已表达
 * 时只剩非零汇差行单独存续（真实既有能力不随表删除）。
 */
@Composable
internal fun FactOffsetSummary(bundle: ExpenseFactBundle) {
    val summary = bundle.financialSummary
    if (summary.status == ExpenseLineageStatus.Confirmed && bundle.activeOffsets.isEmpty()) return
    val root = bundle.root
    val originalDisplay = CurrencyDisplay.forRecord(
        root.originalCurrencyCodeRaw ?: root.originalCurrencyCode.storageKey,
    )
    val homeDisplay = root.recordCurrencyDisplay()
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        val chipRes = when (summary.status) {
            ExpenseLineageStatus.Confirmed -> null
            ExpenseLineageStatus.PartiallyRefunded -> R.string.ledger_lineage_partially_refunded
            ExpenseLineageStatus.FullyRefunded -> R.string.ledger_lineage_fully_refunded
            ExpenseLineageStatus.Reversed -> R.string.ledger_lineage_reversed
        }
        if (chipRes != null) {
            Row {
                StatusPill(text = stringResource(chipRes), active = false)
            }
        }
        FactOffsetSummaryRow(
            label = stringResource(R.string.expense_offset_summary_gross),
            value = formatDisplayAmount(summary.grossOriginalMinor, originalDisplay),
        )
        if (summary.activeRefundedOriginalMinor > 0L) {
            FactOffsetSummaryRow(
                label = stringResource(R.string.expense_offset_summary_refunded),
                value = formatDisplayAmount(summary.activeRefundedOriginalMinor, originalDisplay),
            )
        }
        FactOffsetSummaryRow(
            label = stringResource(R.string.expense_offset_summary_net),
            value = formatDisplayAmount(summary.lineageHomeNetCents, homeDisplay),
        )
        FactOffsetFxDifference(bundle = bundle, homeDisplay = homeDisplay)
    }
}

/** 非零汇差行：hero 抑制汇总表时仍单独存续。 */
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

@Composable
private fun FactOffsetSummaryRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.fillMaxWidth(0.3f),
        )
        Text(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}
