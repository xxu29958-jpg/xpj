package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.exclude
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.LocalAppImeVisible
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals

/**
 * 编辑页操作栏的可见状态（哪些动作可用 + 是否保存中 + 两类提示）。
 *
 * [validationMessage] 是本地表单校验（如"请先填写金额"），永远是错误，用
 * danger 色。[statusMessage] 是异步结果反馈（已保存 / 没有保存成功…），成功
 * 失败混用，保持中性 secondary 色，不染红。
 */
@Immutable
internal data class ExpenseEditActionBarState(
    val saving: Boolean,
    val allowSave: Boolean,
    val allowConfirm: Boolean,
    val allowReject: Boolean,
    val validationMessage: String?,
    val statusMessage: String?,
    val forceCompact: Boolean = false,
)

/** 编辑页操作栏的四个动作回调（沿 BudgetEditorActions 先例分组，避免长参数表）。 */
internal data class ExpenseEditActionBarActions(
    val onBack: () -> Unit,
    val onSave: () -> Unit,
    val onConfirm: () -> Unit,
    val onRequestReject: () -> Unit,
)

/**
 * 编辑页底部浮动操作栏。把原先散落在长表单尾部的「保存 / 确认入账 / 忽略」
 * 合并成永远一拇指可达的单条——最高频的「确认一张票」不再需要滚到底。
 * （动作动词批 15 拍板②统一为「忽略」：草稿不入账、可撤销，区别于真销毁的「删除」；
 *   resource key 沿用既有 `expense_edit_reject_button`，只改文案值。）
 *
 * 层级：
 *  - 主行（前进动作）：保存（tonal outlined）+ 确认入账（filled primary，主操作，
 *    仅 [ExpenseEditActionBarState.allowConfirm]）。
 *  - 次行（低强调）：返回（text）+ 忽略（danger text，仅 allowReject）。
 *  - message 校验/状态提示锚在按钮上沿，"点确认→缺金额"永远在视野内。
 *
 * 软键盘 inset 由外层 [com.ticketbox.ui.components.AppPageScaffold] 的
 * `imePadding()` 统一处理。本栏底部补「导航栏 ∖ 键盘」(navigationBars.exclude(ime))：
 * 键盘收起时补满导航栏高度（浮在系统导航栏之上）；键盘弹出时键盘已覆盖导航栏区域，
 * 这段归零——否则导航栏 inset 会与外层 imePadding 叠加，把底栏顶离键盘、留出空隙。
 */
@Composable
internal fun ExpenseEditActionBar(
    state: ExpenseEditActionBarState,
    actions: ExpenseEditActionBarActions,
) {
    val visuals = LocalThemeVisuals.current
    val keyboardVisible = LocalAppImeVisible.current
    val compactMode = keyboardVisible || state.forceCompact
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .windowInsetsPadding(WindowInsets.navigationBars.exclude(WindowInsets.ime))
            .padding(
                horizontal = AppSpacing.cardGap,
                vertical = AppSpacing.smallGap,
            ),
        shape = RoundedCornerShape(if (compactMode) AppRadius.medium else AppRadius.bottomBar),
        color = visuals.solidCard.copy(alpha = if (compactMode) 0.90f else 0.995f),
        tonalElevation = 0.dp,
        shadowElevation = 0.dp,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(
                    horizontal = AppSpacing.cardPaddingTight,
                    vertical = if (compactMode) AppSpacing.miniGap else AppSpacing.compactGap,
                ),
            verticalArrangement = Arrangement.spacedBy(if (compactMode) AppSpacing.miniGap else AppSpacing.smallGap),
        ) {
            state.validationMessage?.let {
                ExpenseEditActionMessage(it, LocalStateTokens.current.danger.fg)
            }
            state.statusMessage?.let {
                ExpenseEditActionMessage(it, MaterialTheme.colorScheme.secondary)
            }
            if (compactMode) {
                ExpenseEditKeyboardActionRow(state = state, actions = actions)
            } else {
                ExpenseEditActionForwardRow(
                    saving = state.saving,
                    allowSave = state.allowSave,
                    allowConfirm = state.allowConfirm,
                    onSave = actions.onSave,
                    onConfirm = actions.onConfirm,
                )
                ExpenseEditActionSecondaryRow(
                    saving = state.saving,
                    allowReject = state.allowReject,
                    onBack = actions.onBack,
                    onRequestReject = actions.onRequestReject,
                )
            }
        }
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
private fun ExpenseEditActionForwardRow(
    saving: Boolean,
    allowSave: Boolean,
    allowConfirm: Boolean,
    onSave: () -> Unit,
    onConfirm: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        if (allowSave) {
            AppOutlinedButton(
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = AppSpacing.controlMinHeight),
                enabled = !saving,
                onClick = onSave,
            ) {
                ExpenseEditActionLabel(
                    if (saving) {
                        stringResource(R.string.expense_edit_primary_saving_button)
                    } else {
                        stringResource(R.string.expense_edit_primary_save_button)
                    }
                )
            }
        }
        if (allowConfirm) {
            Button(
                modifier = Modifier
                    .weight(if (allowSave) 1.2f else 1f)
                    .heightIn(min = AppSpacing.controlMinHeight),
                enabled = !saving,
                onClick = onConfirm,
            ) {
                ExpenseEditActionLabel(stringResource(R.string.expense_edit_confirm_button))
            }
        }
    }
}

@Composable
private fun ExpenseEditActionSecondaryRow(
    saving: Boolean,
    allowReject: Boolean,
    onBack: () -> Unit,
    onRequestReject: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        AppOutlinedButton(
            modifier = Modifier
                .weight(1f)
                .heightIn(min = AppSpacing.controlMinHeight),
            enabled = !saving,
            onClick = onBack,
        ) {
            ExpenseEditActionLabel(stringResource(R.string.expense_edit_primary_back_button))
        }
        if (allowReject) {
            AppOutlinedButton(
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = AppSpacing.controlMinHeight),
                enabled = !saving,
                danger = true,
                onClick = onRequestReject,
            ) {
                ExpenseEditActionLabel(stringResource(R.string.expense_edit_reject_button))
            }
        }
    }
}

@Composable
private fun ExpenseEditKeyboardActionRow(
    state: ExpenseEditActionBarState,
    actions: ExpenseEditActionBarActions,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        val showBack = !state.allowConfirm || (!state.allowSave && !state.allowReject)
        if (showBack) {
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
                text = stringResource(R.string.expense_edit_reject_button),
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
    AppOutlinedButton(
        modifier = Modifier
            .weight(weight)
            .heightIn(min = AppSpacing.controlMinHeight),
        enabled = enabled,
        contentPadding = CompactActionPadding,
        onClick = onClick,
    ) {
        ExpenseEditActionLabel(text)
    }
}

@Composable
private fun RowScope.CompactFilledAction(
    text: String,
    weight: Float,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Button(
        modifier = Modifier
            .weight(weight)
            .heightIn(min = AppSpacing.controlMinHeight),
        enabled = enabled,
        contentPadding = CompactActionPadding,
        onClick = onClick,
    ) {
        ExpenseEditActionLabel(text)
    }
}

@Composable
private fun RowScope.CompactTextAction(
    text: String,
    weight: Float,
    enabled: Boolean,
    danger: Boolean = false,
    onClick: () -> Unit,
) {
    TextButton(
        modifier = Modifier
            .weight(weight)
            .heightIn(min = AppSpacing.controlMinHeight),
        enabled = enabled,
        contentPadding = CompactActionPadding,
        colors = ButtonDefaults.textButtonColors(
            contentColor = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.48f),
        ),
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
        overflow = TextOverflow.Ellipsis,
    )
}

private val CompactActionPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp)
