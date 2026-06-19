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
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.TagManagementViewModel
import kotlinx.coroutines.delay

/**
 * ADR-0043 slice C — 标签管理 (设置 → 标签管理).
 *
 * 列表 + 使用次数 / 重命名 / 删除 / 合并 + 5s 撤销 banner。Online-only：每次操作后
 * VM 从服务端 reload 权威列表。layout 按移动端形态自决（卡片 + 对话框，不照搬 /web
 * 的表格），token 经 MaterialTheme + AppSpacing + AppGlassCard 三端共享
 * ([[feedback_three_surface_visual_sync]])。
 */
@Composable
fun TagManagementScreen(
    viewModel: TagManagementViewModel,
    readOnly: Boolean,
    onBack: () -> Unit,
    onTagsChanged: () -> Unit = {},
) {
    val state by viewModel.uiState.collectAsState()
    var renaming by remember { mutableStateOf<ManagedTag?>(null) }
    var merging by remember { mutableStateOf<ManagedTag?>(null) }
    var deleting by remember { mutableStateOf<ManagedTag?>(null) }
    var preselectedMergeTarget by remember { mutableStateOf<ManagedTag?>(null) }

    // P4 stale-refresh: after each committed tag mutation, tell the stats tab to
    // re-pull its tag list so a deleted/renamed tag stops lingering in the filter
    // chips. Keyed on the monotonic revision so it re-fires per mutation (>0 guard
    // skips the initial composition).
    LaunchedEffect(state.tagsChangedRevision) {
        if (state.tagsChangedRevision > 0) onTagsChanged()
    }

    // 契约 5: a rename key-collision against a live tag steers into the merge
    // dialog, preselected on the colliding tag (still user-confirmed).
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
        // 契约 5: when a rename steered us here, preselectedMergeTarget carries the
        // server's FRESH conflict token. Splice it over its stale list twin so that
        // tapping that same row in the dialog keeps the fresh row_version (the list
        // copy is from the pre-conflict load) — otherwise re-selecting the preselected
        // target would reintroduce the stale token and the merge would 409 at once.
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
                    Text(stringResource(R.string.tag_management_delete_dialog_confirm), color = MaterialTheme.colorScheme.error)
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
        // ADR-0043 undo: delete/merge are recoverable for a 5s window. Online-only
        // (the handle only exists after a synced mutation); auto-dismisses.
        state.undoable?.let { handle ->
            LaunchedEffect(handle.mutationPublicId) {
                delay(5000)
                viewModel.dismissUndo()
            }
            AppGlassCard(containerAlpha = 0.98f) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(AppSpacing.compactGap),
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
                    // Disabled while a mutate is in flight: a stale undo banner from
                    // an earlier op must not fire concurrently with it (VM also gates).
                    TextButton(enabled = !state.busy, onClick = viewModel::undo) { Text(stringResource(R.string.tag_management_undo_button)) }
                }
            }
        }

        if (readOnly) {
            Text(
                text = stringResource(R.string.tag_management_readonly_hint),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        SettingsSection(title = stringResource(R.string.tag_management_section_all), icon = Icons.Filled.Tune) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                if (state.tags.isEmpty()) {
                    Text(
                        text = stringResource(R.string.tag_management_list_empty),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    state.tags.forEach { tag ->
                        TagCard(
                            tag = tag,
                            readOnly = readOnly,
                            busy = state.busy,
                            canMerge = state.tags.size > 1,
                            onRename = { renaming = tag },
                            onMerge = {
                                preselectedMergeTarget = null
                                merging = tag
                            },
                            onDelete = { deleting = tag },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TagCard(
    tag: ManagedTag,
    readOnly: Boolean,
    busy: Boolean,
    canMerge: Boolean,
    onRename: () -> Unit,
    onMerge: () -> Unit,
    onDelete: () -> Unit,
) {
    AppGlassCard(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(AppSpacing.compactGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = tag.name,
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.width(AppSpacing.compactGap))
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
                    fontWeight = AppTextHierarchy.body.weight,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            if (!readOnly) {
                Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                        onClick = onRename,
                    ) { Text(stringResource(R.string.tag_management_card_action_rename)) }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !busy && canMerge,
                        onClick = onMerge,
                    ) { Text(stringResource(R.string.tag_management_card_action_merge)) }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                        onClick = onDelete,
                    ) { Text(stringResource(R.string.tag_management_card_action_delete)) }
                }
            }
        }
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
    // 契约-5 preselected target seeds here without a remember key.
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
                targets.forEach { target ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .selectable(
                                selected = selected?.publicId == target.publicId,
                                onClick = { selected = target },
                            )
                            .padding(vertical = AppSpacing.smallGap),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(
                            selected = selected?.publicId == target.publicId,
                            onClick = { selected = target },
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
private fun tagSummary(tags: List<ManagedTag>): String {
    if (tags.isEmpty()) return stringResource(R.string.tag_management_summary_empty)
    val orphans = tags.count { it.usageCount == 0 }
    return if (orphans > 0) {
        stringResource(R.string.tag_management_summary_with_orphans, tags.size, orphans)
    } else {
        stringResource(R.string.tag_management_summary_count, tags.size)
    }
}
