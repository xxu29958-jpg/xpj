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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.ui.components.AppGlassCard
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
) {
    val state by viewModel.uiState.collectAsState()
    var renaming by remember { mutableStateOf<ManagedTag?>(null) }
    var merging by remember { mutableStateOf<ManagedTag?>(null) }
    var deleting by remember { mutableStateOf<ManagedTag?>(null) }

    renaming?.let { tag ->
        RenameTagDialog(
            tag = tag,
            onConfirm = { newName ->
                viewModel.renameTag(tag, newName)
                renaming = null
            },
            onDismiss = { renaming = null },
        )
    }
    merging?.let { source ->
        MergeTagDialog(
            source = source,
            targets = state.tags.filter { it.publicId != source.publicId },
            onConfirm = { target ->
                viewModel.mergeTags(source, target)
                merging = null
            },
            onDismiss = { merging = null },
        )
    }
    deleting?.let { tag ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text("删除标签？") },
            text = {
                Text(
                    if (tag.usageCount > 0) {
                        "“${tag.name}”会从 ${tag.usageCount} 笔账单上移除。5 秒内可撤销。"
                    } else {
                        "“${tag.name}”没有任何账单使用，可以安全删除。"
                    },
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    deleting = null
                    viewModel.deleteTag(tag)
                }) {
                    Text("删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deleting = null }) { Text("取消") }
            },
        )
    }

    SettingsPageFrame(
        title = "标签管理",
        subtitle = tagSummary(state.tags),
        onBack = onBack,
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
                        text = "已处理「${handle.label}」",
                        modifier = Modifier.weight(1f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.width(AppSpacing.compactGap))
                    TextButton(onClick = viewModel::undo) { Text("撤销") }
                }
            }
        }

        if (readOnly) {
            Text(
                text = "当前角色为只读，无法修改标签。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        SettingsSection(title = "全部标签", icon = Icons.Filled.Tune) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                if (state.tags.isEmpty()) {
                    Text(
                        text = "还没有标签。记账时给账单添加标签后，这里就能统一整理它们。",
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
                            onMerge = { merging = tag },
                            onDelete = { deleting = tag },
                        )
                    }
                }
            }
        }

        state.message?.takeIf { it.isNotBlank() }?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
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
                    text = if (tag.usageCount > 0) "${tag.usageCount} 笔" else "孤儿",
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
                    ) { Text("重命名") }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !busy && canMerge,
                        onClick = onMerge,
                    ) { Text("合并") }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                        onClick = onDelete,
                    ) { Text("删除") }
                }
            }
        }
    }
}

@Composable
private fun RenameTagDialog(
    tag: ManagedTag,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember { mutableStateOf(tag.name) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("重命名标签") },
        text = {
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("标签名") },
                singleLine = true,
            )
        },
        confirmButton = {
            TextButton(
                enabled = name.trim().isNotBlank() && name.trim() != tag.name,
                onClick = { onConfirm(name) },
            ) { Text("保存") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        },
    )
}

@Composable
private fun MergeTagDialog(
    source: ManagedTag,
    targets: List<ManagedTag>,
    onConfirm: (ManagedTag) -> Unit,
    onDismiss: () -> Unit,
) {
    var selected by remember { mutableStateOf<ManagedTag?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("合并标签") },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 320.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = "把「${source.name}」下的账单改用哪个标签？合并后「${source.name}」会被删除，5 秒内可撤销。",
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
                            text = if (target.usageCount > 0) "${target.name}（${target.usageCount} 笔）" else target.name,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = selected != null,
                onClick = { selected?.let(onConfirm) },
            ) { Text("合并") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        },
    )
}

private fun tagSummary(tags: List<ManagedTag>): String {
    if (tags.isEmpty()) return "暂无标签"
    val orphans = tags.count { it.usageCount == 0 }
    return if (orphans > 0) "共 ${tags.size} 个 · ${orphans} 个孤儿" else "共 ${tags.size} 个标签"
}
