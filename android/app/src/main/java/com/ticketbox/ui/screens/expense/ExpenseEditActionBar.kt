package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Save
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.LocalAppImeVisible
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.forTone
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens

/**
 * 编辑页操作栏的可见状态（哪些动作可用 + 是否保存中 + 两类提示）。
 *
 * [validationMessage] 是本地表单校验（如"请先填写金额"），永远是错误，用
 * danger 色。[statusMessage] 是异步结果反馈（已保存 / 没有保存成功…），颜色由
 * ViewModel 提供的 [statusTone] 决定。
 */
@Immutable
internal data class ExpenseEditActionBarState(
    val saving: Boolean,
    val allowSave: Boolean,
    val allowConfirm: Boolean,
    val allowReject: Boolean,
    val validationMessage: String?,
    val statusMessage: String?,
    val statusTone: MessageTone,
    val forceCompact: Boolean = false,
) {
    val showBackAction: Boolean
        get() = !allowConfirm || (!allowSave && !allowReject)
}

/** 编辑页操作栏的四个动作回调（沿 BudgetEditorActions 先例分组，避免长参数表）。 */
internal data class ExpenseEditActionBarActions(
    val onBack: () -> Unit,
    val onSave: () -> Unit,
    val onConfirm: () -> Unit,
    val onRequestReject: () -> Unit,
)

/**
 * 编辑页底部浮动操作栏。把原先散落在长表单尾部的「保存 / 确认入账 / 忽略或删除」
 * 合并成永远一拇指可达的单条——最高频的「确认一张票」不再需要滚到底。
 * 待确认草稿保留「忽略」语义；已入账记录走「删除」语义。
 *
 * 层级：
 *  - 动作行：忽略/删除（低强调 danger outlined，仅 allowReject）+ 保存（tonal outlined）
 *    + 确认入账（filled primary，主操作，仅 allowConfirm）。返回放在页头，
 *    避免底部重复一个大按钮把二级页压得太重。
 *  - message 校验/状态提示锚在按钮上沿，"点确认→缺金额"永远在视野内。
 *
 * 软键盘 inset 由外层 [com.ticketbox.ui.components.AppPageScaffold] 的
 * `imePadding()` 统一处理。底部浮动栏容器走 `AppFloatingActionBar`，导航栏与键盘
 * inset 只在共享组件里处理，避免每个二级页复制一套避让逻辑。
 */
@Composable
internal fun ExpenseEditActionBar(
    state: ExpenseEditActionBarState,
    actions: ExpenseEditActionBarActions,
) {
    val keyboardVisible = LocalAppImeVisible.current
    val compactMode = keyboardVisible || state.forceCompact
    AppFloatingActionBar(compact = compactMode) {
        state.validationMessage?.let {
            ExpenseEditActionMessage(it, LocalStateTokens.current.danger.fg)
        }
        state.statusMessage?.let {
            ExpenseEditActionMessage(it, LocalStateTokens.current.forTone(state.statusTone).fg)
        }
        ExpenseEditResponsiveActionRows(state = state, actions = actions, compactMode = compactMode)
    }
}

@Composable
private fun ExpenseEditActionMessage(message: String, color: Color) {
    Text(
        text = message,
        color = color,
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun ExpenseEditResponsiveActionRows(
    state: ExpenseEditActionBarState,
    actions: ExpenseEditActionBarActions,
    compactMode: Boolean,
) {
    val actionCount = listOf(state.showBackAction, state.allowReject, state.allowSave, state.allowConfirm).count { it }
    AppAdaptiveEditActionLayout(actionCount = actionCount, compact = compactMode) { mode ->
        when (mode) {
            AppAdaptiveEditActionMode.Stacked -> ExpenseEditStackedActionRows(state = state, actions = actions)
            AppAdaptiveEditActionMode.Compact -> ExpenseEditKeyboardActionRow(state = state, actions = actions)
            AppAdaptiveEditActionMode.Inline -> ExpenseEditActionForwardRow(state = state, actions = actions)
        }
    }
}

@Composable
private fun ExpenseEditStackedActionRows(
    state: ExpenseEditActionBarState,
    actions: ExpenseEditActionBarActions,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        ExpenseEditSecondaryActionRow(state = state, actions = actions)
        if (state.allowConfirm) {
            AppPrimaryButton(
                text = stringResource(R.string.expense_edit_confirm_button),
                icon = Icons.Filled.Check,
                modifier = Modifier.fillMaxWidth(),
                enabled = !state.saving,
                onClick = actions.onConfirm,
            )
        }
    }
}

@Composable
private fun ExpenseEditSecondaryActionRow(
    state: ExpenseEditActionBarState,
    actions: ExpenseEditActionBarActions,
) {
    val rejectText = stringResource(
        if (state.allowConfirm) R.string.expense_edit_ignore_button else R.string.expense_edit_reject_button,
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        if (state.showBackAction) {
            CompactTextAction(
                text = stringResource(R.string.expense_edit_primary_back_button),
                weight = 0.72f,
                enabled = !state.saving,
                onClick = actions.onBack,
            )
        }
        if (state.allowReject) {
            CompactTextAction(
                text = rejectText,
                weight = 0.82f,
                enabled = !state.saving,
                danger = true,
                onClick = actions.onRequestReject,
            )
        }
        if (state.allowSave) {
            CompactOutlinedAction(
                text = if (state.saving) {
                    stringResource(R.string.expense_edit_primary_saving_button)
                } else {
                    stringResource(R.string.expense_edit_primary_save_button)
                },
                weight = 1f,
                enabled = !state.saving,
                onClick = actions.onSave,
            )
        }
    }
}

@Composable
private fun ExpenseEditActionForwardRow(
    state: ExpenseEditActionBarState,
    actions: ExpenseEditActionBarActions,
) {
    val rejectText = stringResource(
        if (state.allowConfirm) R.string.expense_edit_ignore_button else R.string.expense_edit_reject_button,
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (state.showBackAction) {
            CompactTextAction(
                text = stringResource(R.string.expense_edit_primary_back_button),
                weight = 0.72f,
                enabled = !state.saving,
                onClick = actions.onBack,
            )
        }
        if (state.allowReject) {
            CompactTextAction(
                text = rejectText,
                weight = 0.64f,
                enabled = !state.saving,
                danger = true,
                onClick = actions.onRequestReject,
            )
        }
        if (state.allowSave) {
            QuietOutlinedButton(
                modifier = Modifier.weight(if (state.allowConfirm) 0.92f else 1f),
                text = if (state.saving) {
                    stringResource(R.string.expense_edit_primary_saving_button)
                } else {
                    stringResource(R.string.expense_edit_primary_save_button)
                },
                leadingIcon = Icons.Filled.Save,
                enabled = !state.saving,
                onClick = actions.onSave,
            )
        }
        if (state.allowConfirm) {
            AppPrimaryButton(
                text = stringResource(R.string.expense_edit_confirm_button),
                icon = Icons.Filled.Check,
                modifier = Modifier.weight(if (state.allowSave) 1.24f else 1f),
                enabled = !state.saving,
                onClick = actions.onConfirm,
            )
        }
    }
}

@Composable
private fun ExpenseEditKeyboardActionRow(
    state: ExpenseEditActionBarState,
    actions: ExpenseEditActionBarActions,
) {
    val rejectText = stringResource(
        if (state.allowConfirm) R.string.expense_edit_ignore_button else R.string.expense_edit_reject_button,
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        if (state.showBackAction) {
            CompactTextAction(
                text = stringResource(R.string.expense_edit_primary_back_button),
                weight = 0.72f,
                enabled = !state.saving,
                onClick = actions.onBack,
            )
        }
        if (state.allowSave) {
            CompactOutlinedAction(
                text = if (state.saving) {
                    stringResource(R.string.expense_edit_primary_saving_button)
                } else {
                    stringResource(R.string.expense_edit_primary_save_button)
                },
                weight = if (state.allowConfirm) 0.82f else 1f,
                enabled = !state.saving,
                onClick = actions.onSave,
            )
        }
        if (state.allowConfirm) {
            CompactFilledAction(
                text = stringResource(R.string.expense_edit_confirm_button),
                weight = 1.32f,
                enabled = !state.saving,
                onClick = actions.onConfirm,
            )
        }
        if (state.allowReject) {
            CompactTextAction(
                text = rejectText,
                weight = 0.72f,
                enabled = !state.saving,
                danger = true,
                onClick = actions.onRequestReject,
            )
        }
    }
}

@Composable
private fun RowScope.CompactOutlinedAction(
    text: String,
    weight: Float,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    QuietOutlinedButton(
        modifier = Modifier.weight(weight).defaultMinSize(minHeight = 48.dp),
        text = text,
        enabled = enabled,
        onClick = onClick,
    )
}

@Composable
private fun RowScope.CompactFilledAction(
    text: String,
    weight: Float,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    AppPrimaryButton(
        text = text,
        icon = Icons.Filled.Check,
        modifier = Modifier.weight(weight),
        enabled = enabled,
        onClick = onClick,
    )
}

@Composable
private fun RowScope.CompactTextAction(
    text: String,
    weight: Float,
    enabled: Boolean,
    danger: Boolean = false,
    onClick: () -> Unit,
) {
    AppOutlinedButton(
        modifier = Modifier.weight(weight).defaultMinSize(minHeight = 48.dp),
        enabled = enabled,
        danger = danger,
        onClick = onClick,
    ) {
        ExpenseEditActionLabel(text)
    }
}

@Composable
private fun ExpenseEditActionLabel(text: String) {
    Text(
        text = text,
        maxLines = 1,
        softWrap = false,
        autoSize = TextAutoSize.StepBased(minFontSize = 11.sp, maxFontSize = 14.sp, stepSize = 1.sp),
        overflow = TextOverflow.Ellipsis,
    )
}
