package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import com.ticketbox.data.repository.MerchantCreationDraft
import com.ticketbox.data.repository.MerchantCreationKind
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.MerchantCreationState

@Composable
internal fun MerchantCreationReceiptEffect(state: MerchantCreationState, actions: MerchantCreationActions) {
    LaunchedEffect(state.drafts, state.binding, state.busy) {
        if (!state.busy && state.error == null) state.drafts.filter { it.phase == "accepted" && it.binding == state.binding }
            .forEach { actions.onAccepted(it.kind, it.key) }
    }
}

@Composable
internal fun MerchantCreationTask(state: MerchantAliasesScreenState, actions: MerchantAliasesScreenActions, editors: MerchantEditors) {
    val kind = if (editors.activeCreateTool == MerchantCreateTool.Catalog) MerchantCreationKind.Catalog else MerchantCreationKind.Alias
    val creation = state.creation
    val draft = creation.draft(kind)
    val pending = draft != null && draft.phase != "editing"
    SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        MerchantCreationInputs(creation, kind, actions.creation)
        MerchantCreationFeedback(creation, draft, kind, actions.creation)
        AppActionRow(primary = AppAction(
            text = if (pending) "核实原添加" else if (kind == MerchantCreationKind.Catalog) "添加商家" else "添加别名",
            enabled = creation.canSubmit(kind) && !state.busy,
            onClick = { if (kind == MerchantCreationKind.Catalog) actions.catalog.onCreate(draft?.displayName.orEmpty())
                else actions.alias.onCreate(draft?.canonicalMerchant.orEmpty(), draft?.alias.orEmpty()) },
        ), secondary = AppAction(text = "返回", enabled = true, onClick = editors::back))
    }
}

@Composable
private fun MerchantCreationInputs(state: MerchantCreationState, kind: MerchantCreationKind, actions: MerchantCreationActions) {
    val draft = state.draft(kind)
    val readOnly = !state.canEdit(kind)
    if (kind == MerchantCreationKind.Catalog) {
        SettingsDialogTextInput(SettingsTextInputState(label = "商家名称", value = draft?.displayName.orEmpty(),
            placeholder = "如：街角小馆", enabled = state.ready, readOnly = readOnly),
            onValueChange = { actions.onEdit(kind, it, "", "") })
    } else {
        SettingsDialogTextInput(SettingsTextInputState(label = "标准商家名", value = draft?.canonicalMerchant.orEmpty(),
            placeholder = "如：街角小馆", enabled = state.ready, readOnly = readOnly),
            onValueChange = { actions.onEdit(kind, "", it, draft?.alias.orEmpty()) })
        SettingsDialogTextInput(SettingsTextInputState(label = "别名", value = draft?.alias.orEmpty(),
            placeholder = "例如收款记录中的店名", enabled = state.ready, readOnly = readOnly),
            onValueChange = { actions.onEdit(kind, "", draft?.canonicalMerchant.orEmpty(), it) })
    }
}

@Composable
private fun MerchantCreationFeedback(state: MerchantCreationState, draft: MerchantCreationDraft?, kind: MerchantCreationKind, actions: MerchantCreationActions) {
    val changed = draft != null && draft.binding != state.binding
    Text(state.error ?: creationNotice(state, draft), color = MaterialTheme.colorScheme.onSurfaceVariant)
    if (!state.ready && state.error != null) TextButton(enabled = !state.busy, onClick = actions.onReload) { Text("重试读取原稿") }
    if (draft?.phase == "accepted" && state.error != null) TextButton(
        enabled = !changed && !state.busy, onClick = { actions.onAccepted(kind, draft.key) },
    ) { Text("收起已确认的原稿") }
    draft?.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    if (changed || draft?.phase == "rejected") TextButton(enabled = state.canModify && !state.busy, onClick = { actions.onReview(kind) }) {
        Text(if (changed) "核对原身份，继续此任务" else "保留输入，继续修改")
    }
}

private fun creationNotice(state: MerchantCreationState, draft: MerchantCreationDraft?): String = when {
    draft != null && draft.binding != state.binding -> "原身份已变化，输入仍保留。恢复原身份并核对后可继续。"
    draft?.phase == "rejected" -> "原添加已被拒绝。可保留输入继续修改，再次确认后添加。"
    draft?.phase == "accepted" -> "原添加已确认，正在返回商家目录。"
    draft != null && draft.phase != "editing" -> "暂未确认原添加结果。核实将沿用原内容，不会另行添加。"
    !state.ready -> "正在读取此设备保留的原稿…"
    else -> "输入保留在此设备，尚未提交。"
}
