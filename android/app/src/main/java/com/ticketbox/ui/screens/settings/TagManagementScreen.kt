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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Label
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.TagManagementViewModel
import kotlinx.coroutines.delay

private data class TagRowActions(
    val onRename: (ManagedTag) -> Unit,
    val onMerge: (ManagedTag) -> Unit,
    val onDelete: (ManagedTag) -> Unit,
)

@Composable
fun TagManagementScreen(
    viewModel: TagManagementViewModel,
    readOnly: Boolean,
    onBack: () -> Unit,
    onTagsChanged: () -> Unit = {},
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var renaming by remember { mutableStateOf<ManagedTag?>(null) }
    var merging by remember { mutableStateOf<ManagedTag?>(null) }
    var deleting by remember { mutableStateOf<ManagedTag?>(null) }
    var preselectedMergeTarget by remember { mutableStateOf<ManagedTag?>(null) }
    val actions = remember {
        TagRowActions(
            onRename = { tag -> renaming = tag },
            onMerge = { tag ->
                preselectedMergeTarget = null
                merging = tag
            },
            onDelete = { tag -> deleting = tag },
        )
    }

    // After a committed tag mutation, refresh stats filters that may still show old names.
    LaunchedEffect(state.tagsChangedRevision) {
        if (state.tagsChangedRevision > 0) onTagsChanged()
    }

    // Rename collisions become an explicit user-confirmed merge.
    LaunchedEffect(state.mergeSuggestion) {
        state.mergeSuggestion?.let { suggestion ->
            preselectedMergeTarget = suggestion.target
            merging = suggestion.source
            viewModel.consumeMergeSuggestion()
        }
    }

    renaming?.let { tag ->
        RenameTagDialog(
            tag = tag,
            busy = state.busy,
            onConfirm = { newName ->
                viewModel.renameTag(tag, newName)
                renaming = null
            },
            onDismiss = { renaming = null },
        )
    }
    merging?.let { source ->
        // Preserve the fresh conflict token returned by the server for the preselected target.
        val freshTarget = preselectedMergeTarget
        val mergeTargets = state.tags
            .filter { it.publicId != source.publicId }
            .map { if (freshTarget != null && it.publicId == freshTarget.publicId) freshTarget else it }
        MergeTagDialog(
            source = source,
            targets = mergeTargets,
            initialTarget = freshTarget,
            busy = state.busy,
            onConfirm = { target ->
                viewModel.mergeTags(source, target)
                merging = null
                preselectedMergeTarget = null
            },
            onDismiss = {
                merging = null
                preselectedMergeTarget = null
            },
        )
    }
    deleting?.let { tag ->
        AlertDialog(
            onDismissRequest = { deleting = null },
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
                TextButton(
                    enabled = !state.busy,
                    onClick = {
                        deleting = null
                        viewModel.deleteTag(tag)
                    },
                ) {
                    Text(
                        text = stringResource(R.string.tag_management_delete_dialog_confirm),
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
            dismissButton = {
                TextButton(onClick = { deleting = null }) { Text(stringResource(R.string.common_cancel)) }
            },
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.tag_management_page_title),
        subtitle = tagSummary(state.tags),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = MessageTone.Neutral) },
    ) {
        state.undoable?.let { handle ->
            TagUndoPanel(handle = handle, busy = state.busy, onUndo = viewModel::undo)
            LaunchedEffect(handle.mutationPublicId) {
                delay(5000)
                viewModel.dismissUndo()
            }
        }
        if (readOnly) {
            SettingsInlineEmpty(
                title = stringResource(R.string.tag_management_readonly_title),
                body = stringResource(R.string.tag_management_readonly_hint),
            )
        }
        TagOverviewSection(tags = state.tags)
        TagListSection(
            tags = state.tags,
            readOnly = readOnly,
            busy = state.busy,
            actions = actions,
        )
    }
}

@Composable
private fun TagUndoPanel(
    handle: com.ticketbox.viewmodel.TagUndoHandle,
    busy: Boolean,
    onUndo: () -> Unit,
) {
    SettingsOpenPanel {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = AppSpacing.miniGap),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = stringResource(R.string.tag_management_undo_processed, handle.label),
                modifier = Modifier.weight(1f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.width(AppSpacing.compactGap))
            TextButton(enabled = !busy, onClick = onUndo) {
                Text(stringResource(R.string.tag_management_undo_button))
            }
        }
    }
}

@Composable
private fun TagOverviewSection(tags: List<ManagedTag>) {
    val summary = remember(tags) { tagManagementSummaryModel(tags) }
    SettingsSection(
        title = stringResource(R.string.tag_management_section_overview),
        icon = Icons.AutoMirrored.Filled.Label,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                TagOverviewMetric(
                    label = stringResource(R.string.tag_management_overview_total_label),
                    value = summary.totalCount,
                    caption = stringResource(R.string.tag_management_overview_total_caption),
                    modifier = Modifier.weight(1f),
                )
                TagOverviewMetric(
                    label = stringResource(R.string.tag_management_overview_active_label),
                    value = summary.activeCount,
                    caption = stringResource(R.string.tag_management_overview_active_caption),
                    modifier = Modifier.weight(1f),
                )
                TagOverviewMetric(
                    label = stringResource(R.string.tag_management_overview_unused_label),
                    value = summary.unusedCount,
                    caption = stringResource(R.string.tag_management_overview_unused_caption),
                    modifier = Modifier.weight(1f),
                )
            }
            Text(
                text = stringResource(R.string.tag_management_overview_body),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun TagOverviewMetric(
    label: String,
    value: Int,
    caption: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
        )
        Text(
            text = value.toString(),
            style = MaterialTheme.typography.titleMedium.tabularNum(),
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
        )
        Text(
            text = caption,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 2,
        )
    }
}

@Composable
private fun TagListSection(
    tags: List<ManagedTag>,
    readOnly: Boolean,
    busy: Boolean,
    actions: TagRowActions,
) {
    SettingsSection(title = stringResource(R.string.tag_management_section_all), icon = Icons.Filled.Tune) {
        if (tags.isEmpty()) {
            SettingsInlineEmpty(
                title = stringResource(R.string.tag_management_summary_empty),
                body = stringResource(R.string.tag_management_list_empty),
            )
            return@SettingsSection
        }
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(0.dp)) {
            tags.forEachIndexed { index, tag ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
                }
                TagRow(
                    tag = tag,
                    readOnly = readOnly,
                    busy = busy,
                    canMerge = tags.size > 1,
                    actions = actions,
                )
            }
        }
    }
}

@Composable
private fun TagRow(
    tag: ManagedTag,
    readOnly: Boolean,
    busy: Boolean,
    canMerge: Boolean,
    actions: TagRowActions,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = tag.name,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = if (tag.usageCount > 0) {
                    stringResource(R.string.tag_management_card_usage_count, tag.usageCount)
                } else {
                    stringResource(R.string.tag_management_card_orphan)
                },
                color = if (tag.usageCount > 0) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    MaterialTheme.colorScheme.primary
                },
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
            )
        }
        if (!readOnly) {
            TagActionMenu(tag = tag, busy = busy, canMerge = canMerge, actions = actions)
        }
    }
}

@Composable
private fun TagActionMenu(
    tag: ManagedTag,
    busy: Boolean,
    canMerge: Boolean,
    actions: TagRowActions,
) {
    var expanded by remember(tag.publicId) { mutableStateOf(false) }
    IconButton(
        enabled = !busy,
        onClick = { expanded = true },
    ) {
        Icon(
            imageVector = Icons.Filled.MoreVert,
            contentDescription = stringResource(R.string.tag_management_actions_content_description),
        )
    }
    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
        DropdownMenuItem(
            text = { Text(stringResource(R.string.tag_management_card_action_rename)) },
            onClick = {
                expanded = false
                actions.onRename(tag)
            },
        )
        DropdownMenuItem(
            text = { Text(stringResource(R.string.tag_management_card_action_merge)) },
            enabled = canMerge,
            onClick = {
                expanded = false
                actions.onMerge(tag)
            },
        )
        DropdownMenuItem(
            text = {
                Text(
                    text = stringResource(R.string.tag_management_card_action_delete),
                    color = MaterialTheme.colorScheme.error,
                )
            },
            onClick = {
                expanded = false
                actions.onDelete(tag)
            },
        )
    }
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
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.tag_management_rename_dialog_label)) },
                singleLine = true,
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

@Composable
private fun MergeTagDialog(
    source: ManagedTag,
    targets: List<ManagedTag>,
    onConfirm: (ManagedTag) -> Unit,
    onDismiss: () -> Unit,
    initialTarget: ManagedTag? = null,
    busy: Boolean = false,
) {
    // Fresh per dialog open (the merging?.let block re-enters composition), so the
    // contract preselected target seeds here without a remember key.
    var selected by remember { mutableStateOf(initialTarget) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.tag_management_merge_dialog_title)) },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 320.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = stringResource(R.string.tag_management_merge_dialog_text, source.name),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.width(AppSpacing.tinyGap))
                MergeTargetPicker(targets = targets, selected = selected, onSelected = { selected = it })
            }
        },
        confirmButton = {
            TextButton(
                enabled = !busy && selected != null,
                onClick = { selected?.let(onConfirm) },
            ) { Text(stringResource(R.string.tag_management_merge_dialog_confirm)) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
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

@Composable
private fun tagSummary(tags: List<ManagedTag>): String {
    val summary = tagManagementSummaryModel(tags)
    if (summary.totalCount == 0) return stringResource(R.string.tag_management_summary_empty)
    return if (summary.unusedCount > 0) {
        stringResource(R.string.tag_management_summary_with_unused, summary.totalCount, summary.unusedCount)
    } else {
        stringResource(R.string.tag_management_summary_count, summary.totalCount)
    }
}
