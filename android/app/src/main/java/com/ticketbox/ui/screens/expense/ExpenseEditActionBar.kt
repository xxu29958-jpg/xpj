package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppOutlinedButton
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
)

/** 编辑页操作栏的四个动作回调（沿 BudgetEditorActions 先例分组，避免长参数表）。 */
internal data class ExpenseEditActionBarActions(
    val onBack: () -> Unit,
    val onSave: () -> Unit,
    val onConfirm: () -> Unit,
    val onRequestReject: () -> Unit,
)

/**
 * 编辑页底部浮动操作栏。把原先散落在长表单尾部的「保存 / 确认入账 / 删除」
 * 合并成永远一拇指可达的单条——最高频的「确认一张票」不再需要滚到底。
 * （删除的动词最终定名见批 15 拍板②，本批不动既有 `expense_edit_reject_button`。）
 *
 * 层级：
 *  - 主行（前进动作）：保存（tonal outlined）+ 确认入账（filled primary，主操作，
 *    仅 [ExpenseEditActionBarState.allowConfirm]）。
 *  - 次行（低强调）：返回（text）+ 删除（danger text，仅 allowReject）。
 *  - message 校验/状态提示锚在按钮上沿，"点确认→缺金额"永远在视野内。
 *
 * 软键盘 inset 由外层 [com.ticketbox.ui.components.AppPageScaffold] 的
 * `imePadding()` 统一处理，本栏只补导航栏 inset（镜像 AppBottomNav）。
 */
@Composable
internal fun ExpenseEditActionBar(
    state: ExpenseEditActionBarState,
    actions: ExpenseEditActionBarActions,
) {
    val visuals = LocalThemeVisuals.current
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(
                horizontal = AppSpacing.cardGap,
                vertical = AppSpacing.smallGap,
            ),
        shape = RoundedCornerShape(AppRadius.bottomBar),
        color = visuals.solidCard.copy(alpha = 0.995f),
        tonalElevation = 0.dp,
        shadowElevation = 0.dp,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.compactGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            state.validationMessage?.let {
                ExpenseEditActionMessage(it, LocalStateTokens.current.danger.fg)
            }
            state.statusMessage?.let {
                ExpenseEditActionMessage(it, MaterialTheme.colorScheme.secondary)
            }
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
                modifier = Modifier.weight(1f),
                enabled = !saving,
                onClick = onSave,
            ) {
                Text(
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
                modifier = Modifier.weight(if (allowSave) 1.2f else 1f),
                enabled = !saving,
                onClick = onConfirm,
            ) {
                Text(stringResource(R.string.expense_edit_confirm_button))
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
            modifier = Modifier.weight(1f),
            enabled = !saving,
            onClick = onBack,
        ) {
            Text(stringResource(R.string.expense_edit_primary_back_button))
        }
        if (allowReject) {
            AppOutlinedButton(
                modifier = Modifier.weight(1f),
                enabled = !saving,
                danger = true,
                onClick = onRequestReject,
            ) {
                Text(stringResource(R.string.expense_edit_reject_button))
            }
        }
    }
}
