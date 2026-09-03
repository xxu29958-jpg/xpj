package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

internal const val TAG_TIME_ROW = "expense-edit-time-row"

internal data class ExpenseEditTimeRowState(
    val expenseTime: String,
    val baselineExpenseTime: String,
    val enabled: Boolean = true,
)

internal data class ExpenseEditTimeRowActions(
    val onPickDate: () -> Unit,
    val onPickTime: () -> Unit,
    val onUseNow: () -> Unit,
    val onUndoChange: () -> Unit,
)

/**
 * 是否出现「撤销修改」：仅当本场编辑把草稿改离了已存值。baseline null 与
 * 空串同义（初始空不是修改）。这是草稿恢复，不是事实清除——当前 nullable
 * PATCH（exclude_unset）没有清除已存时间的命令，不提供那种按钮。
 */
internal fun expenseEditTimeModifiedSinceBaseline(current: String, baseline: String?): Boolean =
    current != baseline.orEmpty()

/**
 * 消费时间行：点行开日期 picker（主路径），行内安静动作「选时间 / 设为现在」，
 * 草稿被改离已存值时再出「撤销修改」回到已存值。
 */
@Composable
internal fun ExpenseEditTimeRow(
    state: ExpenseEditTimeRowState,
    actions: ExpenseEditTimeRowActions,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = stringResource(R.string.expense_edit_date_section_title),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.body.weight,
        )
        ExpenseEditTimeValueRow(
            expenseTime = state.expenseTime,
            enabled = state.enabled,
            onClick = actions.onPickDate,
        )
        if (state.enabled) {
            ExpenseEditTimeQuietActions(state = state, actions = actions)
        }
    }
}

@Composable
private fun ExpenseEditTimeValueRow(
    expenseTime: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val hasTime = expenseTime.isNotBlank()
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .testTag(TAG_TIME_ROW)
            .clickable(
                enabled = enabled,
                onClickLabel = stringResource(R.string.expense_edit_date_pick_date_button),
                role = Role.Button,
                onClick = onClick,
            )
            .defaultMinSize(minHeight = AppSpacing.controlMinHeight),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = if (hasTime) {
                displayDateTime(expenseTime)
            } else {
                stringResource(R.string.expense_edit_time_unset)
            },
            modifier = Modifier.weight(1f),
            color = if (hasTime) {
                MaterialTheme.colorScheme.onSurface
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            style = MaterialTheme.typography.bodyLarge,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        if (enabled) {
            Icon(
                imageVector = Icons.Filled.ExpandMore,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ExpenseEditTimeQuietActions(
    state: ExpenseEditTimeRowState,
    actions: ExpenseEditTimeRowActions,
) {
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        QuietOutlinedButton(
            text = stringResource(R.string.expense_edit_date_pick_time_button),
            onClick = actions.onPickTime,
        )
        QuietOutlinedButton(
            text = stringResource(R.string.expense_edit_date_use_now_button),
            onClick = actions.onUseNow,
        )
        if (expenseEditTimeModifiedSinceBaseline(state.expenseTime, state.baselineExpenseTime)) {
            QuietOutlinedButton(
                text = stringResource(R.string.expense_edit_undo_change_button),
                onClick = actions.onUndoChange,
            )
        }
    }
}
