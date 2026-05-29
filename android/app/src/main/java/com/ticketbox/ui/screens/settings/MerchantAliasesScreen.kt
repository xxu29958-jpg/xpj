package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import kotlinx.coroutines.delay

@Composable
fun MerchantAliasesScreen(
    aliases: List<MerchantAlias>,
    busy: Boolean,
    readOnly: Boolean,
    message: String?,
    onBack: () -> Unit,
    onCreateAlias: (String, String) -> Unit,
    onToggleAlias: (MerchantAlias) -> Unit,
    onDeleteAlias: (MerchantAlias) -> Unit,
    undoableAlias: MerchantAlias? = null,
    onUndoDelete: () -> Unit = {},
    onDismissUndo: () -> Unit = {},
) {
    var canonicalMerchant by remember { mutableStateOf("") }
    var aliasText by remember { mutableStateOf("") }
    var localMessage by remember { mutableStateOf<String?>(null) }
    var deletingAlias by remember { mutableStateOf<MerchantAlias?>(null) }

    deletingAlias?.let { item ->
        AlertDialog(
            onDismissRequest = { deletingAlias = null },
            title = { Text("删除这个别名？") },
            text = { Text("删除后，“${item.alias}”不再自动归到“${item.canonicalMerchant}”。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        deletingAlias = null
                        onDeleteAlias(item)
                    },
                ) {
                    Text("删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deletingAlias = null }) {
                    Text("取消")
                }
            },
        )
    }

    SettingsPageFrame(
        title = "商家别名",
        subtitle = merchantAliasSummary(aliases),
        onBack = onBack,
    ) {
        // ADR-0038 undo: a soft-deleted alias is recoverable for a 5s window.
        // Online-only (only shown after a synced delete); auto-dismisses.
        undoableAlias?.let { undoable ->
            LaunchedEffect(undoable.publicId) {
                delay(5000)
                onDismissUndo()
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
                        text = "已删除「${undoable.alias}」",
                        modifier = Modifier.weight(1f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.width(AppSpacing.compactGap))
                    TextButton(onClick = onUndoDelete) { Text("撤销") }
                }
            }
        }

        if (!readOnly) {
            SettingsSection(title = "新增别名", icon = Icons.Filled.Tune) {
                AppGlassCard(containerAlpha = 0.96f) {
                    Column(
                        modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                    ) {
                        OutlinedTextField(
                            value = canonicalMerchant,
                            onValueChange = { canonicalMerchant = it },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text("标准商家名") },
                            placeholder = { Text("星巴克") },
                            singleLine = true,
                        )
                        OutlinedTextField(
                            value = aliasText,
                            onValueChange = { aliasText = it },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text("别名") },
                            placeholder = { Text("Starbucks") },
                            singleLine = true,
                        )
                        Button(
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !busy,
                            onClick = {
                                if (canonicalMerchant.isBlank() || aliasText.isBlank()) {
                                    localMessage = "请填写标准商家名和别名。"
                                    return@Button
                                }
                                localMessage = null
                                onCreateAlias(canonicalMerchant, aliasText)
                                canonicalMerchant = ""
                                aliasText = ""
                            },
                        ) {
                            Text(if (busy) "处理中" else "添加别名")
                        }
                        localMessage?.let {
                            Text(it, color = MaterialTheme.colorScheme.secondary)
                        }
                    }
                }
            }
        } else {
            Text(
                text = "当前角色为只读，无法修改账本。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        SettingsSection(title = "别名列表", icon = Icons.Filled.Tune) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                if (aliases.isEmpty()) {
                    Text(
                        text = "暂无商家别名。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    aliases.forEach { item ->
                        MerchantAliasCard(
                            alias = item,
                            readOnly = readOnly,
                            busy = busy,
                            onToggleAlias = { onToggleAlias(item) },
                            onDeleteAlias = { deletingAlias = item },
                        )
                    }
                }
            }
        }

        message?.takeIf { it.isNotBlank() }?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
    }
}

@Composable
private fun MerchantAliasCard(
    alias: MerchantAlias,
    readOnly: Boolean,
    busy: Boolean,
    onToggleAlias: () -> Unit,
    onDeleteAlias: () -> Unit,
) {
    AppGlassCard(containerAlpha = 0.98f) {
        Column(modifier = Modifier.padding(AppSpacing.compactGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                    Text(
                        text = alias.alias,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = "归到 ${alias.canonicalMerchant}",
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.bodyMedium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Spacer(Modifier.width(AppSpacing.compactGap))
                Text(
                    text = if (alias.enabled) "已启用" else "已停用",
                    color = if (alias.enabled) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    fontWeight = AppTextHierarchy.body.weight,
                )
            }
            Text(
                text = "${alias.aliasKey} -> ${alias.canonicalKey}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (!readOnly) {
                Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                        onClick = onToggleAlias,
                    ) {
                        Text(if (alias.enabled) "停用" else "启用")
                    }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                        onClick = onDeleteAlias,
                    ) {
                        Text("删除")
                    }
                }
            }
        }
    }
}

private fun merchantAliasSummary(aliases: List<MerchantAlias>): String {
    val enabled = aliases.count { it.enabled }
    return if (aliases.isEmpty()) {
        "暂无别名"
    } else {
        "$enabled 条启用 · 共 ${aliases.size} 条"
    }
}
