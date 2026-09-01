package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.ExpenseOffsetChangeKind
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.StreamOffsetKind
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.ExpenseFactViewModel
import com.ticketbox.viewmodel.loadExpenseFactBundle
import com.ticketbox.viewmodel.openOffsetSheet
import com.ticketbox.viewmodel.openVoidOffsetSheet

/**
 * Refund/Chargeback/Reversal 纵向片：事实详情「退回与冲销」段（紧随摘要卡）。
 * 原账单保持不变；退回/冲销是追加的一等事实行。金额、净额、状态、影响全部
 * 渲染服务端 bundle，客户端不重算。
 *
 * 币种纪律（共同冻结）：original 口径（gross/refunded/offset 金额）用
 * `CurrencyDisplay.forRecord(原币码)`（未知码原样亮码）；`lineageHomeNetCents`、
 * `fxDifferenceCents`、accepted share 是 home 口径，用 root.recordCurrencyDisplay()。
 * 动作区不依赖 read model：只有真实 Loaded 的 bundle status 才构成
 * fully-refunded/reversed gate；Failed/Loading 的旧快照不得禁 command。
 */
@Composable
internal fun FactOffsetsSection(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
    AppSectionHeader(
        title = stringResource(R.string.expense_fact_offsets_title),
        subtitle = stringResource(R.string.expense_fact_offsets_hint),
    )
    // 状态诚实（共同裁决）：先渲染已知 bundle；null+Loading 给轻量加载表达；
    // Failed 无论有无 bundle 都给诚实文案+retry（有 bundle 说明显示的是已知记录）；
    // queued intent chip 独立于 bundle 永远渲染 —— 离线排队恰好常伴随 bundle 不可读。
    val bundle = state.factBundle
    if (bundle != null) {
        FactOffsetsLoaded(state = state, bundle = bundle, viewModel = viewModel)
    } else if (state.factBundleLoadState == ExpenseDetailDataLoadState.Loading) {
        Text(
            text = stringResource(R.string.expense_fact_offsets_loading),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
    if (state.factBundleLoadState == ExpenseDetailDataLoadState.Failed) {
        FactOffsetsFailed(
            message = state.factBundleMessage,
            showsKnownRecords = bundle != null,
            onRetry = viewModel::loadExpenseFactBundle,
        )
    }
    state.pendingOffsetIntent?.let { intent ->
        StatusPill(
            text = listOfNotNull(
                intent.offsetKind?.let { offsetKindLabel(it) },
                stringResource(R.string.expense_offset_pending_sync),
            ).joinToString(" · "),
            active = false,
            tone = LocalStateTokens.current.info,
        )
    }
    // command 不依赖 read model（Product Owner 裁决）：已知 confirmed root + 写权限即可。
    if (!state.readOnly && state.expense != null) {
        FactOffsetActions(state = state, viewModel = viewModel)
    }
}

@Composable
private fun FactOffsetsFailed(message: UiText?, showsKnownRecords: Boolean, onRetry: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = if (showsKnownRecords) {
                stringResource(R.string.expense_fact_offsets_stale)
            } else {
                message?.asString() ?: stringResource(R.string.expense_fact_offsets_failed)
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.weight(1f),
        )
        TextButton(onClick = onRetry) {
            Text(text = stringResource(R.string.common_retry))
        }
    }
}

@Composable
private fun FactOffsetsLoaded(
    state: ExpenseFactUiState,
    bundle: ExpenseFactBundle,
    viewModel: ExpenseFactViewModel,
) {
    val homeDisplay = bundle.root.recordCurrencyDisplay()
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        FactOffsetSummary(bundle = bundle)
        if (bundle.activeOffsets.isEmpty() &&
            bundle.financialSummary.status == ExpenseLineageStatus.Confirmed
        ) {
            Text(
                text = stringResource(R.string.expense_offset_empty),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        bundle.activeOffsets.forEach { offset ->
            FactOffsetActiveRow(
                offset = offset,
                canWrite = !state.readOnly,
                onVoid = { viewModel.openVoidOffsetSheet(offset) },
            )
        }
        FactOffsetImpacts(bundle = bundle, homeDisplay = homeDisplay)
        FactOffsetHistory(bundle = bundle)
    }
}

@Composable
private fun FactOffsetSummary(bundle: ExpenseFactBundle) {
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
        if (summary.fxDifferenceCents != 0L) {
            Text(
                text = stringResource(
                    R.string.expense_offset_summary_fx_difference,
                    formatDisplayAmount(summary.fxDifferenceCents, homeDisplay),
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
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

@Composable
private fun FactOffsetActiveRow(
    offset: ExpenseOffsetFact,
    canWrite: Boolean,
    onVoid: () -> Unit,
) {
    // offset 金额按自身原币码渲染（forRecord：未知码原样亮码，不拿 home 符号撒谎）。
    val originalDisplay = CurrencyDisplay.forRecord(offset.originalCurrencyCode)
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                StatusPill(text = offsetKindLabel(offset.kind), active = false)
                Text(
                    text = "+" + formatDisplayAmount(offset.originalAmountMinor, originalDisplay),
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            Text(
                text = listOf(offset.accountingDate, offset.reason)
                    .filter { it.isNotBlank() }
                    .joinToString(" · "),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        if (canWrite) {
            TextButton(onClick = onVoid) {
                Text(text = stringResource(R.string.expense_offset_void_action))
            }
        }
    }
}

@Composable
private fun FactOffsetImpacts(bundle: ExpenseFactBundle, homeDisplay: CurrencyDisplay) {
    val impacts = bundle.relationshipImpacts
    if (impacts.pendingInvitesCancelled.isEmpty() && impacts.acceptedImpacts.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        if (impacts.pendingInvitesCancelled.isNotEmpty()) {
            Text(
                text = stringResource(
                    R.string.expense_offset_impact_cancelled,
                    impacts.pendingInvitesCancelled.size,
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        impacts.acceptedImpacts.forEach { impact ->
            Text(
                text = stringResource(
                    R.string.expense_offset_impact_accepted_line,
                    impact.receiverDisplayName
                        ?: stringResource(R.string.expense_fact_timeline_member_unknown),
                    formatDisplayAmount(impact.originalAgreedShareHomeMinor, homeDisplay),
                    formatDisplayAmount(impact.suggestedNetShareHomeMinor, homeDisplay),
                ),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Text(
            text = stringResource(R.string.expense_offset_impact_disclaimer),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun FactOffsetHistory(bundle: ExpenseFactBundle) {
    if (bundle.recentHistory.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        bundle.recentHistory.forEach { revision ->
            val kindLabel = stringResource(
                when (revision.changeKind) {
                    ExpenseOffsetChangeKind.Created -> R.string.expense_offset_history_created
                    ExpenseOffsetChangeKind.Correction -> R.string.expense_offset_history_correction
                    ExpenseOffsetChangeKind.Void -> R.string.expense_offset_history_void
                },
            )
            Text(
                text = listOf(kindLabel, displayDateTime(revision.createdAt), revision.reason)
                    .filter { it.isNotBlank() }
                    .joinToString(" · "),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun FactOffsetActions(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
    // 只有当前 bundle 真实 Loaded，status 才构成 gate；Failed/Loading 时旧快照
    // 不得继续禁 command（eligibility 归服务端，remaining 只作预填/提示）。
    val status = state.factBundle
        ?.takeIf { state.factBundleLoadState == ExpenseDetailDataLoadState.Loaded }
        ?.financialSummary
        ?.status
    if (status == ExpenseLineageStatus.Reversed) {
        Text(
            text = stringResource(R.string.expense_offset_reversed_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        AppPrimaryButton(
            text = stringResource(R.string.expense_offset_create_refund_cta),
            icon = Icons.Filled.Add,
            modifier = Modifier.fillMaxWidth(),
            enabled = status != ExpenseLineageStatus.FullyRefunded,
            onClick = { viewModel.openOffsetSheet(StreamOffsetKind.Refund) },
        )
        // reversal gate（共同裁决）：server resolve_offset_money 在存在任一 active
        // refund/chargeback 时稳定 409 expense_refund_exists。Loaded 且 partial/fully
        // 时不渲染冲销动作，改给「先撤销」指引；status 未知（Loading/Failed）不用
        // 旧快照 gate，照常渲染由 server 终裁。
        if (status == null || status == ExpenseLineageStatus.Confirmed) {
            AppSecondaryButton(
                text = stringResource(R.string.expense_offset_create_reversal_cta),
                modifier = Modifier.fillMaxWidth(),
                onClick = { viewModel.openOffsetSheet(StreamOffsetKind.Reversal) },
            )
        } else {
            Text(
                text = stringResource(R.string.expense_offset_reversal_blocked_hint),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

/** kind 人话标签（段内行与 sheet 共用；ledger 列表另有短文案 chip）。 */
@Composable
internal fun offsetKindLabel(kind: StreamOffsetKind): String = stringResource(
    when (kind) {
        StreamOffsetKind.Refund -> R.string.expense_offset_kind_refund
        StreamOffsetKind.Chargeback -> R.string.expense_offset_kind_chargeback
        StreamOffsetKind.Reversal -> R.string.expense_offset_kind_reversal
    },
)
