package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.ui.design.AppSpacing

internal data class TagManagementDialogState(
    val renaming: ManagedTag?,
    val merging: ManagedTag?,
    val deleting: ManagedTag?,
    val tags: List<ManagedTag>,
    val preselectedMergeTarget: ManagedTag?,
    val busy: Boolean,
)

internal data class TagManagementDialogActions(
    val onRenameConfirm: (ManagedTag, String) -> Unit,
    val onMergeConfirm: (ManagedTag, ManagedTag) -> Unit,
    val onDeleteConfirm: (ManagedTag) -> Unit,
    val onDismissRename: () -> Unit,
    val onDismissMerge: () -> Unit,
    val onDismissDelete: () -> Unit,
)

@Composable
internal fun TagManagementDialogHost(
    state: TagManagementDialogState,
    actions: TagManagementDialogActions,
) {
    state.renaming?.let { tag ->
        RenameTagDialog(
            tag = tag,
            busy = state.busy,
            onConfirm = { newName -> actions.onRenameConfirm(tag, newName) },
            onDismiss = actions.onDismissRename,
        )
    }
    state.merging?.let { source ->
        MergeTagDialog(
            state = MergeTagDialogState(
                source = source,
                targets = mergeTargetOptions(
                    tags = state.tags,
                    source = source,
                    freshTarget = state.preselectedMergeTarget,
                ),
                initialTarget = state.preselectedMergeTarget,
                busy = state.busy,
            ),
            actions = MergeTagDialogActions(
                onConfirm = { target -> actions.onMergeConfirm(source, target) },
                onDismiss = actions.onDismissMerge,
            ),
        )
    }
    state.deleting?.let { tag ->
        DeleteTagDialog(
            tag = tag,
            busy = state.busy,
            onConfirm = { actions.onDeleteConfirm(tag) },
            onDismiss = actions.onDismissDelete,
        )
    }
}

@Composable
private fun DeleteTagDialog(
    tag: ManagedTag,
    busy: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.tag_management_delete_dialog_title)) },
        text = {
            Text(
                if (tag.usageCount > 0) {
                    stringResource(R.string.tag_management_delete_dialog_text_used, tag.name, tag.usageCount)
                } else {
                    stringResource(R.string.tag_management_delete_dialog_text_unused, tag.name)
                },
            )
        },
        confirmButton = {
            TextButton(enabled = !busy, onClick = onConfirm) {
                Text(
                    text = stringResource(R.string.tag_management_delete_dialog_confirm),
                    color = MaterialTheme.colorScheme.error,
                )
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

@Composable
private fun RenameTagDialog(
    tag: ManagedTag,
    busy: Boolean,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember { mutableStateOf(tag.name) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.tag_management_rename_dialog_title)) },
        text = {
            SettingsDialogTextInput(
                state = SettingsTextInputState(
                    label = stringResource(R.string.tag_management_rename_dialog_label),
                    value = name,
                    enabled = !busy,
                ),
                onValueChange = { name = it },
                modifier = Modifier.fillMaxWidth(),
            )
        },
        confirmButton = {
            TextButton(
                enabled = !busy && name.trim().isNotBlank() && name.trim() != tag.name,
                onClick = { onConfirm(name) },
            ) { Text(stringResource(R.string.tag_management_rename_dialog_confirm)) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

private data class MergeTagDialogState(
    val source: ManagedTag,
    val targets: List<ManagedTag>,
    val initialTarget: ManagedTag?,
    val busy: Boolean,
)

private data class MergeTagDialogActions(
    val onConfirm: (ManagedTag) -> Unit,
    val onDismiss: () -> Unit,
)

@Composable
private fun MergeTagDialog(
    state: MergeTagDialogState,
    actions: MergeTagDialogActions,
) {
    // Fresh per dialog open, so the contract preselected target seeds here without a remember key.
    var selected by remember { mutableStateOf(state.initialTarget) }
    AlertDialog(
        onDismissRequest = actions.onDismiss,
        title = { Text(stringResource(R.string.tag_management_merge_dialog_title)) },
        text = {
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
                Spacer(Modifier.height(AppSpacing.tinyGap))
                MergeTargetPicker(targets = state.targets, selected = selected, onSelected = { selected = it })
            }
        },
        confirmButton = {
            TextButton(
                enabled = !state.busy && selected != null,
                onClick = { selected?.let(actions.onConfirm) },
            ) { Text(stringResource(R.string.tag_management_merge_dialog_confirm)) }
        },
        dismissButton = {
            TextButton(onClick = actions.onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

@Composable
private fun MergeTargetPicker(
    targets: List<ManagedTag>,
    selected: ManagedTag?,
    onSelected: (ManagedTag) -> Unit,
) {
    targets.forEach { target ->
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .selectable(
                    selected = selected?.publicId == target.publicId,
                    onClick = { onSelected(target) },
                )
                .padding(vertical = AppSpacing.smallGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RadioButton(
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
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
