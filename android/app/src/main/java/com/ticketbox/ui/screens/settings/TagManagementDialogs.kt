package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.TagEditorAction
import com.ticketbox.viewmodel.TagEditorDraft

internal data class TagManagementDialogState(
    val editor: TagEditorDraft?,
    val tags: List<ManagedTag>,
    val busy: Boolean,
    val readOnly: Boolean,
    val bindingChanged: Boolean,
    val message: UiText?,
    val messageTone: MessageTone,
)

internal data class TagManagementDialogActions(
    val onRenameConfirm: (ManagedTag, String) -> Unit,
    val onMergeConfirm: (ManagedTag, ManagedTag) -> Unit,
    val onDeleteConfirm: (ManagedTag) -> Unit,
    val onEdit: (TagEditorDraft?) -> Unit,
)

@Composable
internal fun TagManagementDialogHost(
    state: TagManagementDialogState,
    actions: TagManagementDialogActions,
) {
    val editor = state.editor ?: return
    val tag = editor.source
    when (editor.action) {
        TagEditorAction.Rename -> RenameTagDialog(
            tag = tag,
            state = state,
            onConfirm = { newName -> actions.onRenameConfirm(tag, newName) },
            onEdit = { actions.onEdit(editor.copy(name = it)) },
            onDismiss = { actions.onEdit(null) },
        )
        TagEditorAction.Merge -> MergeTagDialog(
            state = MergeTagDialogState(
                source = tag,
                targets = mergeTargetOptions(
                    tags = state.tags,
                    source = tag,
                    freshTarget = editor.target,
                ),
                selected = editor.target,
                busy = state.busy,
                readOnly = state.readOnly,
                bindingChanged = state.bindingChanged,
                message = state.message,
                messageTone = state.messageTone,
            ),
            actions = MergeTagDialogActions(
                onConfirm = { target -> actions.onMergeConfirm(tag, target) },
                onSelected = { actions.onEdit(editor.copy(target = it)) },
                onDismiss = { actions.onEdit(null) },
            ),
        )
        TagEditorAction.Delete -> DeleteTagDialog(
            tag = tag,
            state = state,
            onConfirm = { actions.onDeleteConfirm(tag) },
            onDismiss = { actions.onEdit(null) },
        )
    }
}

@Composable
private fun DeleteTagDialog(
    tag: ManagedTag,
    state: TagManagementDialogState,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = { if (!state.busy) onDismiss() },
        title = { Text(stringResource(R.string.tag_management_delete_dialog_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(
                    if (tag.usageCount > 0) {
                        stringResource(R.string.tag_management_delete_dialog_text_used, tag.name, tag.usageCount)
                    } else {
                        stringResource(R.string.tag_management_delete_dialog_text_unused, tag.name)
                    },
                )
                AppStatusBanner(message = state.message, tone = state.messageTone)
                TagDraftAccessMessage(state.readOnly, state.bindingChanged)
            }
        },
        confirmButton = {
            TextButton(enabled = !state.busy && !state.readOnly, onClick = onConfirm) {
                Text(
                    text = stringResource(R.string.tag_management_delete_dialog_confirm),
                    color = MaterialTheme.colorScheme.error,
                )
            }
        },
        dismissButton = {
            TextButton(enabled = !state.busy, onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

@Composable
private fun RenameTagDialog(
    tag: ManagedTag,
    state: TagManagementDialogState,
    onConfirm: (String) -> Unit,
    onEdit: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val name = state.editor?.name.orEmpty()
    AlertDialog(
        onDismissRequest = { if (!state.busy) onDismiss() },
        title = { Text(stringResource(R.string.tag_management_rename_dialog_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                SettingsDialogTextInput(
                    state = SettingsTextInputState(
                        label = stringResource(R.string.tag_management_rename_dialog_label),
                        value = name,
                        enabled = !state.busy,
                    ),
                    onValueChange = onEdit,
                    modifier = Modifier.fillMaxWidth(),
                )
                AppStatusBanner(message = state.message, tone = state.messageTone)
                TagDraftAccessMessage(state.readOnly, state.bindingChanged)
            }
        },
        confirmButton = {
            TextButton(
                enabled = !state.busy && !state.readOnly && name.trim().isNotBlank() && name.trim() != tag.name,
                onClick = { onConfirm(name) },
            ) { Text(stringResource(R.string.tag_management_rename_dialog_confirm)) }
        },
        dismissButton = {
            TextButton(enabled = !state.busy, onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

private data class MergeTagDialogState(
    val source: ManagedTag,
    val targets: List<ManagedTag>,
    val selected: ManagedTag?,
    val busy: Boolean,
    val readOnly: Boolean,
    val bindingChanged: Boolean,
    val message: UiText?,
    val messageTone: MessageTone,
)

private data class MergeTagDialogActions(
    val onConfirm: (ManagedTag) -> Unit,
    val onSelected: (ManagedTag) -> Unit,
    val onDismiss: () -> Unit,
)

@Composable
private fun MergeTagDialog(
    state: MergeTagDialogState,
    actions: MergeTagDialogActions,
) {
    AlertDialog(
        onDismissRequest = { if (!state.busy) actions.onDismiss() },
        title = { Text(stringResource(R.string.tag_management_merge_dialog_title)) },
        text = { MergeTagDialogBody(state, actions.onSelected) },
        confirmButton = {
            TextButton(
                enabled = !state.busy && !state.readOnly && state.selected != null,
                onClick = { state.selected?.let(actions.onConfirm) },
            ) { Text(stringResource(R.string.tag_management_merge_dialog_confirm)) }
        },
        dismissButton = {
            TextButton(enabled = !state.busy, onClick = actions.onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

@Composable
private fun MergeTagDialogBody(state: MergeTagDialogState, onSelected: (ManagedTag) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        AppStatusBanner(message = state.message, tone = state.messageTone)
        TagDraftAccessMessage(state.readOnly, state.bindingChanged)
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(max = AppSpacing.controlMinHeight * 8)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = stringResource(R.string.tag_management_merge_dialog_text, state.source.name),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
            MergeTargetPicker(state.targets, state.selected, !state.busy, onSelected)
            Text(
                text = stringResource(R.string.tag_management_merge_dialog_consequences),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
private fun TagDraftAccessMessage(readOnly: Boolean, bindingChanged: Boolean) {
    if (!readOnly) return
    AppStatusBanner(
        message = UiText.res(if (bindingChanged) R.string.tag_management_draft_binding_changed else R.string.tag_management_draft_readonly),
        tone = MessageTone.Info,
    )
}

@Composable
private fun MergeTargetPicker(
    targets: List<ManagedTag>,
    selected: ManagedTag?,
    enabled: Boolean,
    onSelected: (ManagedTag) -> Unit,
) {
    targets.forEach { target ->
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .selectable(
                    enabled = enabled,
                    selected = selected?.publicId == target.publicId,
                    onClick = { onSelected(target) },
                )
                .padding(vertical = AppSpacing.smallGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RadioButton(
                enabled = enabled,
                selected = selected?.publicId == target.publicId,
                onClick = { onSelected(target) },
            )
            Spacer(Modifier.width(AppSpacing.smallGap))
            Text(
                text = if (target.usageCount > 0) {
                    stringResource(R.string.tag_management_merge_dialog_target_with_count, target.name, target.usageCount)
                } else {
                    target.name
                },
            )
        }
    }
}
