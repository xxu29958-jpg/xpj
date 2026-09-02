package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.ExpenseFactUiState

/**
 * W2-B 详情金额呈现合同（与 Codex 共同冻结，三点一组）：
 * 1. 有已知 bundle 且 lineage 非 Confirmed → hero 稳定展示 server-owned 净额；
 *    query 刷新中/失败不摘已知投影（新鲜度由段内 stale/failed 文案表达）。
 *    command eligibility 的 Loaded 纪律不借用给展示。
 * 2. 净额 hero 的伴生行 = 原始口径金额（· 已退回），original 币种 display。
 * 3. 普通外币账单（无 bundle/Confirmed 但有原币金额且原币≠home）→ hero 下
 *    保留「原始 USD 10.00」伴生行，原币事实不得从详情消失；净额/home 仍用
 *    recordCurrencyDisplay，客户端不做换算。
 * 4. bundle 未载（离线/首读，退款状况未知）→ hero 金额旁标「原账金额」口径；
 *    不虚构退款/净额。bundle 已知 Confirmed 的普通账单保持无标签。
 */
internal fun factHeroShowsNet(bundle: ExpenseFactBundle?): Boolean =
    bundle != null && bundle.financialSummary.status != ExpenseLineageStatus.Confirmed

internal fun factHeroShowsOriginal(expense: Expense, showsNet: Boolean): Boolean {
    if (showsNet) return true
    expense.originalAmountMinor ?: return false
    val originalCode = expense.originalCurrencyCodeRaw ?: expense.originalCurrencyCode.storageKey
    val homeCode = expense.homeCurrencyCode ?: expense.homeCurrency.storageKey
    return originalCode != homeCode
}

/** hero 金额旁的口径伴生：不让同一个无标签大数字随 query 态换含义。 */
internal enum class FactHeroCaption {
    None,
    Gross,
    Original,
    GrossOriginal,
    Net,
}

internal fun factHeroCaptionKind(expense: Expense, bundle: ExpenseFactBundle?): FactHeroCaption {
    if (factHeroShowsNet(bundle)) return FactHeroCaption.Net
    val showsOriginal = factHeroShowsOriginal(expense, showsNet = false)
    return when {
        // bundle 未载（离线/首读）：只能保证根账单金额，标「原账金额」口径，
        // 不虚构退款/净额；普通无退回账单（bundle 已知 Confirmed）保持干净。
        bundle == null && showsOriginal -> FactHeroCaption.GrossOriginal
        bundle == null -> FactHeroCaption.Gross
        showsOriginal -> FactHeroCaption.Original
        else -> FactHeroCaption.None
    }
}

/**
 * W2-B 事实 hero：商家是标题，金额是重心（有退回/冲销时为净额 + 原始口径
 * 伴生行），分类/时间/来源收成一行 meta。只读事实字段表只保留未被 hero
 * 覆盖的项；「更正这笔账单」仍是摘要段唯一写入口。
 */
@Composable
internal fun FactSummarySection(
    expense: Expense,
    state: ExpenseFactUiState,
    onOpenCorrection: () -> Unit,
) {
    val display = expense.recordCurrencyDisplay()
    val showsNet = factHeroShowsNet(state.factBundle)
    val empty = stringResource(R.string.expense_fact_value_empty)
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = expense.merchant?.takeIf { it.isNotBlank() } ?: empty,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.SemiBold,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            StatusPill(text = stringResource(R.string.expense_fact_status_confirmed))
            if (showsNet) {
                val chipRes = when (state.factBundle?.financialSummary?.status) {
                    ExpenseLineageStatus.PartiallyRefunded -> R.string.ledger_lineage_partially_refunded
                    ExpenseLineageStatus.FullyRefunded -> R.string.ledger_lineage_fully_refunded
                    else -> R.string.ledger_lineage_reversed
                }
                StatusPill(text = stringResource(chipRes), active = false)
            }
            if (expense.factRevision > 1) {
                StatusPill(
                    text = stringResource(R.string.expense_fact_revision_badge, expense.factRevision),
                    active = false,
                )
            }
        }
        FactHeroAmount(expense = expense, state = state, showsNet = showsNet, homeDisplay = display)
        FactMetaLine(expense = expense)
    }

    FactFieldRows(expense = expense)

    if (state.readOnly) {
        Text(
            text = stringResource(R.string.expense_fact_readonly_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    } else {
        AppPrimaryButton(
            text = stringResource(R.string.expense_fact_correct_cta),
            icon = Icons.Filled.Edit,
            onClick = onOpenCorrection,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun FactHeroAmount(
    expense: Expense,
    state: ExpenseFactUiState,
    showsNet: Boolean,
    homeDisplay: CurrencyDisplay,
) {
    val bundle = state.factBundle
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = if (showsNet && bundle != null) {
                formatDisplayAmount(bundle.financialSummary.lineageHomeNetCents, homeDisplay)
            } else {
                formatDisplayAmount(expense.amountCents, homeDisplay)
            },
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.displaySmall.tabularNum(),
        )
        val caption = factHeroCaption(expense = expense, bundle = bundle, showsNet = showsNet)
        if (caption != null) {
            Text(
                text = caption,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

/** hero 伴生行：净额态给「原始 X · 已退回 Y」；普通外币账单给「原始 USD 10.00」；
 *  bundle 未载时先标「原账金额」口径。 */
@Composable
private fun factHeroCaption(
    expense: Expense,
    bundle: ExpenseFactBundle?,
    showsNet: Boolean,
): String? {
    val originalDisplay = CurrencyDisplay.forRecord(
        expense.originalCurrencyCodeRaw ?: expense.originalCurrencyCode.storageKey,
    )
    if (showsNet && bundle != null) {
        val summary = bundle.financialSummary
        return listOfNotNull(
            stringResource(
                R.string.expense_fact_hero_original_caption,
                formatDisplayAmount(summary.grossOriginalMinor, originalDisplay),
            ),
            if (summary.activeRefundedOriginalMinor > 0L) {
                stringResource(
                    R.string.expense_fact_hero_refunded_caption,
                    formatDisplayAmount(summary.activeRefundedOriginalMinor, originalDisplay),
                )
            } else {
                null
            },
        ).joinToString(" · ")
    }
    val grossLabel = stringResource(R.string.expense_fact_hero_gross_caption)
    val originalCaption = if (factHeroShowsOriginal(expense, showsNet = false)) {
        val originalMinor = expense.originalAmountMinor ?: return null
        stringResource(
            R.string.expense_fact_hero_original_caption,
            formatDisplayAmount(originalMinor, originalDisplay),
        )
    } else {
        null
    }
    return when (factHeroCaptionKind(expense, bundle)) {
        FactHeroCaption.Gross -> grossLabel
        FactHeroCaption.GrossOriginal -> listOfNotNull(grossLabel, originalCaption).joinToString(" · ")
        FactHeroCaption.Original -> originalCaption
        else -> null
    }
}

/** 分类 · 消费时间 · 来源 —— 一行可扫读的 meta，不再是字段表行。 */
@Composable
private fun FactMetaLine(expense: Expense) {
    val parts = listOfNotNull(
        expense.category.takeIf { it.isNotBlank() },
        expense.expenseTime?.let { displayDateTime(it) },
        expense.source.takeIf { it.isNotBlank() },
    )
    if (parts.isEmpty()) return
    Text(
        text = parts.joinToString(" · "),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
        maxLines = 2,
        overflow = TextOverflow.Ellipsis,
    )
}

/** 只保留 hero/meta 未覆盖的事实字段；空值可选字段直接省略（缺备注不是事件）。 */
@Composable
private fun FactFieldRows(expense: Expense) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        expense.tags?.takeIf { it.isNotBlank() }?.let {
            FactFieldRow(label = stringResource(R.string.expense_fact_field_tags), value = it)
        }
        expense.note?.takeIf { it.isNotBlank() }?.let {
            FactFieldRow(label = stringResource(R.string.expense_fact_field_note), value = it)
        }
        FactScoreFieldRow(expense = expense)
        FactFieldRow(
            label = stringResource(R.string.expense_fact_field_created),
            value = displayDateTime(expense.createdAt),
        )
        expense.confirmedAt?.takeIf { it.isNotBlank() }?.let { confirmedAt ->
            FactFieldRow(
                label = stringResource(R.string.expense_fact_field_confirmed_at),
                value = displayDateTime(confirmedAt),
            )
        }
    }
}

@Composable
private fun FactFieldRow(label: String, value: String) {
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
private fun FactScoreFieldRow(expense: Expense) {
    if (expense.valueScore == null && expense.regretScore == null) return
    val empty = stringResource(R.string.expense_fact_value_empty)
    FactFieldRow(
        label = stringResource(R.string.expense_fact_field_score),
        value = stringResource(
            R.string.expense_fact_score_pair,
            expense.valueScore?.let { stringResource(R.string.expense_fact_score_format, it) } ?: empty,
            expense.regretScore?.let { stringResource(R.string.expense_fact_score_format, it) } ?: empty,
        ),
    )
}
