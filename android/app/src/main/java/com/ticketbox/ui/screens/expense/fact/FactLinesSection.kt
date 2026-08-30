package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.SkeletonBlock
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState

/**
 * A1 明细/拆账只读段：事实呈现，不出现会 409 的旧 PUT 编辑入口；
 * 修改路径统一指向「更正这笔账单」。唯一例外：mismatch_known 时明细卡片给出
 * 「原小票如此」状态确认命令（非字段编辑，走既有 revision/OCC owner），
 * 只读角色不渲染该动作。
 */
@Composable
internal fun FactLinesSection(
    state: ExpenseFactUiState,
    onRetryItems: () -> Unit,
    onRetrySplits: () -> Unit,
    onAcknowledgeItems: () -> Unit,
) {
    val expense = state.expense ?: return
    val display = expense.recordCurrencyDisplay()
    FactItemsCard(
        state = state,
        display = display,
        onRetry = onRetryItems,
        onAcknowledgeItems = onAcknowledgeItems,
    )
    FactSplitsCard(state = state, display = display, onRetry = onRetrySplits)
}

@Composable
private fun FactItemsCard(
    state: ExpenseFactUiState,
    display: com.ticketbox.domain.model.CurrencyDisplay,
    onRetry: () -> Unit,
    onAcknowledgeItems: () -> Unit,
) {
    val items = state.expenseItems
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        AppSectionHeader(title = stringResource(R.string.expense_fact_items_title))
        Text(
            text = stringResource(R.string.expense_fact_items_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        when (state.itemsLoadState) {
            ExpenseDetailDataLoadState.Loading -> {
                SkeletonBlock(modifier = Modifier.fillMaxWidth().height(AppSpacing.sectionGap))
            }
            ExpenseDetailDataLoadState.Failed -> {
                Text(
                    text = state.itemsMessage?.asString()
                        ?: stringResource(R.string.expense_fact_items_failed),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                TextButton(onClick = onRetry) {
                    Text(text = stringResource(R.string.expense_fact_retry))
                }
            }
            else -> {
                if (items != null && items.hasMismatch) {
                    FactItemsMismatchAffordance(
                        items = items,
                        display = display,
                        readOnly = state.readOnly,
                        itemsLoading = state.itemsLoading,
                        onAcknowledgeItems = onAcknowledgeItems,
                    )
                }
                val rows = items?.items.orEmpty()
                if (rows.isEmpty()) {
                    Text(
                        text = stringResource(R.string.expense_fact_items_empty),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                } else {
                    rows.forEach { item ->
                        FactItemRow(item = item, display = display)
                    }
                }
            }
        }
    }
}

/**
 * 明细差异供能组：差异文案 + 终态/命令入口。
 * mismatch_acknowledged 给诚实终态文案；mismatch_known + 写权限给真实
 * 「原小票如此」命令（次级 TextButton，在途禁用），只读不渲染动作。
 */
@Composable
private fun FactItemsMismatchAffordance(
    items: ExpenseItems,
    display: com.ticketbox.domain.model.CurrencyDisplay,
    readOnly: Boolean,
    itemsLoading: Boolean,
    onAcknowledgeItems: () -> Unit,
) {
    Text(
        text = stringResource(
            R.string.expense_fact_items_mismatch,
            formatDisplayAmount(items.mismatchCents, display),
        ),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
    if (items.mismatchAcknowledged) {
        Text(
            text = stringResource(R.string.expense_edit_v1_items_mismatch_acknowledged),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    } else if (items.mismatchKnown && !readOnly) {
        TextButton(
            onClick = onAcknowledgeItems,
            enabled = !itemsLoading,
        ) {
            Text(text = stringResource(R.string.expense_edit_v1_items_mismatch_ack_button))
        }
    }
}

@Composable
private fun FactItemRow(
    item: com.ticketbox.domain.model.ExpenseItem,
    display: com.ticketbox.domain.model.CurrencyDisplay,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = item.name,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.weight(1f),
        )
        item.quantityText?.takeIf { it.isNotBlank() }?.let { quantity ->
            Text(
                text = quantity,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Text(
            text = formatDisplayAmount(item.amountCents, display),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
        )
        Text(
            text = stringResource(
                when (item.kind) {
                    ExpenseItemKind.DISCOUNT -> R.string.expense_edit_items_kind_discount
                    ExpenseItemKind.TAX -> R.string.expense_edit_items_kind_tax
                    ExpenseItemKind.SERVICE_FEE -> R.string.expense_edit_items_kind_service_fee
                    else -> R.string.expense_edit_items_kind_product
                },
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun FactSplitsCard(
    state: ExpenseFactUiState,
    display: com.ticketbox.domain.model.CurrencyDisplay,
    onRetry: () -> Unit,
) {
    val splits = state.expenseSplits
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        AppSectionHeader(title = stringResource(R.string.expense_fact_splits_title))
        Text(
            text = stringResource(R.string.expense_fact_splits_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        when (state.splitsLoadState) {
            ExpenseDetailDataLoadState.Loading -> {
                SkeletonBlock(modifier = Modifier.fillMaxWidth().height(AppSpacing.sectionGap))
            }
            ExpenseDetailDataLoadState.Failed -> {
                Text(
                    text = state.splitsMessage?.asString()
                        ?: stringResource(R.string.expense_fact_splits_failed),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                TextButton(onClick = onRetry) {
                    Text(text = stringResource(R.string.expense_fact_retry))
                }
            }
            else -> {
                FactSplitsReconcileLine(splits = splits, display = display)
                val rows = splits?.splits.orEmpty()
                if (rows.isEmpty()) {
                    Text(
                        text = stringResource(R.string.expense_fact_splits_empty),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                } else {
                    rows.forEach { split ->
                        FactSplitRow(split = split, display = display)
                    }
                }
            }
        }
    }
}

@Composable
private fun FactSplitsReconcileLine(
    splits: com.ticketbox.domain.model.ExpenseSplits?,
    display: com.ticketbox.domain.model.CurrencyDisplay,
) {
    if (splits == null || splits.splitsTotalAmountCents == null) return
    val mismatch = splits.mismatchCents
    val isOverallocated = mismatch != null && mismatch < 0L
    Text(
        text = when {
            mismatch == null || mismatch == 0L -> {
                stringResource(
                    R.string.expense_fact_splits_reconcile,
                    formatDisplayAmount(splits.parentAmountCents, display),
                    formatDisplayAmount(splits.splitsTotalAmountCents, display),
                )
            }
            mismatch > 0L -> {
                stringResource(
                    R.string.expense_fact_splits_reconcile_partial,
                    formatDisplayAmount(splits.parentAmountCents, display),
                    formatDisplayAmount(splits.splitsTotalAmountCents, display),
                    formatDisplayAmount(mismatch, display),
                )
            }
            else -> {
                stringResource(
                    R.string.expense_fact_splits_reconcile_overallocated,
                    formatDisplayAmount(splits.parentAmountCents, display),
                    formatDisplayAmount(splits.splitsTotalAmountCents, display),
                    formatDisplayAmount(kotlin.math.abs(mismatch), display),
                )
            }
        },
        color = if (isOverallocated) {
            MaterialTheme.colorScheme.error
        } else {
            MaterialTheme.colorScheme.onSurfaceVariant
        },
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun FactSplitRow(
    split: com.ticketbox.domain.model.ExpenseSplit,
    display: com.ticketbox.domain.model.CurrencyDisplay,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = split.accountName + if (split.disabledAt != null) {
                stringResource(R.string.expense_fact_split_member_disabled)
            } else {
                ""
            },
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.weight(1f),
        )
        Text(
            text = formatDisplayAmount(split.amountCents, display),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}
