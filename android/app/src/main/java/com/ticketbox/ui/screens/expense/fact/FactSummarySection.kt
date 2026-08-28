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
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.ExpenseFactUiState

/**
 * A1 事实摘要段：金额 hero + 状态行 + 只读事实定义列表 + 唯一写入口
 * 「更正这笔账单」。普通用户第一眼知道这是什么、下一步去哪 —— 不是字段堆叠。
 */
@Composable
internal fun FactSummarySection(
    expense: Expense,
    state: ExpenseFactUiState,
    onOpenCorrection: () -> Unit,
) {
    val display = expense.recordCurrencyDisplay()
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = formatDisplayAmount(expense.amountCents, display),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.displaySmall,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            StatusPill(text = stringResource(R.string.expense_fact_status_confirmed))
            if (expense.factRevision > 1) {
                StatusPill(
                    text = stringResource(R.string.expense_fact_revision_badge, expense.factRevision),
                    active = false,
                )
            }
        }
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
private fun FactFieldRows(expense: Expense) {
    val empty = stringResource(R.string.expense_fact_value_empty)
    val display = expense.recordCurrencyDisplay()
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        FactFieldRow(
            label = stringResource(R.string.expense_fact_field_amount),
            value = expense.originalAmountMinor?.let { minor ->
                "${expense.originalCurrencyCode} ${formatDisplayAmount(minor, display)}"
            } ?: empty,
        )
        FactFieldRow(
            label = stringResource(R.string.expense_fact_field_merchant),
            value = expense.merchant?.takeIf { it.isNotBlank() } ?: empty,
        )
        FactFieldRow(
            label = stringResource(R.string.expense_fact_field_category),
            value = expense.category.takeIf { it.isNotBlank() } ?: empty,
        )
        FactScoreFieldRow(expense = expense, empty = empty)
        FactFieldRow(
            label = stringResource(R.string.expense_fact_field_time),
            value = expense.expenseTime?.let { displayDateTime(it) } ?: empty,
        )
        FactFieldRow(
            label = stringResource(R.string.expense_fact_field_tags),
            value = expense.tags?.takeIf { it.isNotBlank() } ?: empty,
        )
        FactFieldRow(
            label = stringResource(R.string.expense_fact_field_note),
            value = expense.note?.takeIf { it.isNotBlank() } ?: empty,
        )
        FactFieldRow(
            label = stringResource(R.string.expense_fact_field_source),
            value = expense.source.takeIf { it.isNotBlank() } ?: empty,
        )
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
private fun FactScoreFieldRow(expense: Expense, empty: String) {
    if (expense.valueScore == null && expense.regretScore == null) return
    FactFieldRow(
        label = stringResource(R.string.expense_fact_field_score),
        value = stringResource(
            R.string.expense_fact_score_pair,
            expense.valueScore?.let { stringResource(R.string.expense_fact_score_format, it) } ?: empty,
            expense.regretScore?.let { stringResource(R.string.expense_fact_score_format, it) } ?: empty,
        ),
    )
}
