package com.ticketbox.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.ui.components.formatStorageSize
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState

@Composable
fun SettingsScreen(
    state: SettingsUiState,
    currentSkin: AppSkin,
    onTestConnection: () -> Unit,
    onRunDiagnostics: () -> Unit,
    onRefreshServerSettings: () -> Unit,
    onSync: () -> Unit,
    onClearCache: () -> Unit,
    onCreateRule: (String, String, Int) -> Unit,
    onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    onToggleRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
    onSkinChange: (AppSkin) -> Unit,
    onBindingCleared: () -> Unit,
) {
    var keyword by remember { mutableStateOf("") }
    var category by remember { mutableStateOf("") }
    var priorityText by remember { mutableStateOf("10") }
    var editingRule by remember { mutableStateOf<CategoryRule?>(null) }
    var localMessage by remember { mutableStateOf<String?>(null) }
    var showServerStatusDetails by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        Text("设置", style = MaterialTheme.typography.headlineSmall)

        SettingSection(title = "外观") {
            AppSkin.entries.chunked(2).forEach { rowSkins ->
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    rowSkins.forEach { skin ->
                        SkinOptionCard(
                            modifier = Modifier.weight(1f),
                            skin = skin,
                            selected = skin == currentSkin,
                            onClick = { onSkinChange(skin) },
                        )
                    }
                    if (rowSkins.size == 1) {
                        Spacer(modifier = Modifier.weight(1f))
                    }
                }
            }
        }

        SettingSection(title = "连接") {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.72f),
                ),
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text("当前服务器", style = MaterialTheme.typography.labelLarge)
                    Text(
                        text = state.serverUrl ?: "未绑定",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(
                    modifier = Modifier.weight(1f),
                    onClick = onTestConnection,
                ) {
                    Text(if (state.busy) "处理中" else "测试连接")
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    onClick = onRunDiagnostics,
                ) {
                    Text("联调自检")
                }
            }
        }
        state.diagnostics?.let { diagnostics ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        text = "自检结果：通过 ${diagnostics.passedCount} · 警告 ${diagnostics.warningCount} · 失败 ${diagnostics.failedCount}",
                        style = MaterialTheme.typography.titleSmall,
                    )
                    diagnostics.checks.forEach { check ->
                        val color = when (check.status) {
                            DiagnosticStatus.Pass -> MaterialTheme.colorScheme.primary
                            DiagnosticStatus.Warn -> MaterialTheme.colorScheme.tertiary
                            DiagnosticStatus.Fail -> MaterialTheme.colorScheme.error
                        }
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(check.name, color = color)
                                Text("${check.elapsedMs} ms", color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text(check.detail, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
        SettingSection(title = "维护") {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    onClick = onSync,
                ) {
                    Text("重新同步")
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    onClick = onClearCache,
                ) {
                    Text("清缓存")
                }
            }
        }

        SettingSection(title = "服务器状态") {
            state.serverSettings?.let { serverSettings ->
                ServerStatusCard(
                    serverSettings = serverSettings,
                    expanded = showServerStatusDetails,
                    onToggleExpanded = { showServerStatusDetails = !showServerStatusDetails },
                )
            } ?: Text("服务器状态未加载", color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedButton(
                modifier = Modifier.fillMaxWidth(),
                onClick = onRefreshServerSettings,
            ) {
                Text("刷新")
            }
        }

        Text("自动分类规则", style = MaterialTheme.typography.titleMedium)
        OutlinedTextField(
            value = keyword,
            onValueChange = { keyword = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("关键词") },
            placeholder = { Text("OpenAI") },
            singleLine = true,
        )
        OutlinedTextField(
            value = category,
            onValueChange = { category = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("分类") },
            placeholder = { Text("AI订阅") },
            singleLine = true,
        )
        OutlinedTextField(
            value = priorityText,
            onValueChange = { priorityText = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("优先级") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            singleLine = true,
        )
        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = {
                val priority = priorityText.toIntOrNull()
                if (priority == null) {
                    localMessage = "优先级必须是数字。"
                    return@Button
                }
                localMessage = null
                val currentEditing = editingRule
                if (currentEditing == null) {
                    onCreateRule(keyword, category, priority)
                } else {
                    onUpdateRule(currentEditing, keyword, category, priority)
                }
                keyword = ""
                category = ""
                priorityText = "10"
                editingRule = null
            },
        ) {
            Text(if (editingRule == null) "添加分类规则" else "保存分类规则")
        }
        if (editingRule != null) {
            OutlinedButton(
                modifier = Modifier.fillMaxWidth(),
                onClick = {
                    keyword = ""
                    category = ""
                    priorityText = "10"
                    editingRule = null
                },
            ) {
                Text("取消编辑")
            }
        }
        if (state.categoryRules.isEmpty()) {
            Text("暂无分类规则", color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            state.categoryRules.forEach { rule ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(rule.keyword, style = MaterialTheme.typography.titleSmall)
                            Text(rule.category, color = MaterialTheme.colorScheme.primary)
                        }
                        Text(
                            text = "优先级 ${rule.priority} · ${if (rule.enabled) "已启用" else "已停用"}",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        OutlinedButton(onClick = { onToggleRule(rule) }) {
                            Text(if (rule.enabled) "停用" else "启用")
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(
                                onClick = {
                                    editingRule = rule
                                    keyword = rule.keyword
                                    category = rule.category
                                    priorityText = rule.priority.toString()
                                },
                            ) {
                                Text("编辑")
                            }
                            OutlinedButton(onClick = { onDeleteRule(rule) }) {
                                Text("删除")
                            }
                        }
                    }
                }
            }
        }

        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = {
                onBindingCleared()
            },
        ) {
            Text("清除服务器绑定")
        }

        state.message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
        localMessage?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
        Text("关于小票夹：私人截图确认账本，第一版不做自动入账。")
    }
}

@Composable
private fun ServerStatusCard(
    serverSettings: ServerSettings,
    expanded: Boolean,
    onToggleExpanded: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.72f),
        ),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "账单 ${serverSettings.pendingCount} / ${serverSettings.confirmedCount} / ${serverSettings.rejectedCount}",
                style = MaterialTheme.typography.titleSmall,
            )
            Text(
                text = "图片 ${formatStorageSize(serverSettings.uploadStorageBytes)} · OCR ${serverSettings.ocrProvider}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (expanded) {
                Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text("上传限制：${serverSettings.maxUploadSizeMb} MB")
                    Text("缩略图：${if (serverSettings.generateThumbnail) "已启用" else "未启用"}")
                    Text("确认后删原图：${if (serverSettings.deleteImageAfterConfirm) "已启用" else "未启用"}")
                    Text("保留天数：${serverSettings.deleteImageAfterDays}")
                    Text("疑似重复：${serverSettings.suspectedDuplicateCount}")
                }
            }
            OutlinedButton(
                modifier = Modifier.fillMaxWidth(),
                onClick = onToggleExpanded,
            ) {
                Text(if (expanded) "收起详情" else "查看详情")
            }
        }
    }
}

@Composable
private fun SettingSection(
    title: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        content()
    }
}

@Composable
private fun SkinOptionCard(
    modifier: Modifier = Modifier,
    skin: AppSkin,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val scheme = colorSchemeForSkin(skin)
    val containerColor = if (selected) {
        scheme.primary.copy(alpha = 0.22f)
    } else {
        MaterialTheme.colorScheme.surface.copy(alpha = 0.68f)
    }
    val borderColor = if (selected) scheme.primary else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.72f)

    Card(
        modifier = modifier.height(118.dp),
        onClick = onClick,
        colors = CardDefaults.cardColors(containerColor = containerColor),
        border = BorderStroke(1.dp, borderColor),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(12.dp),
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            SkinSwatches(scheme)
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = skin.displayName,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 1,
                    )
                    if (selected) {
                        Text(
                            text = "当前",
                            color = scheme.primary,
                            style = MaterialTheme.typography.labelSmall,
                        )
                    }
                }
                Text(
                    text = skin.description,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun SkinSwatches(scheme: ColorScheme) {
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        listOf(
            scheme.primary,
            scheme.secondary,
            scheme.tertiary,
            scheme.surfaceVariant,
        ).forEach { color ->
            Box(
                modifier = Modifier
                    .size(20.dp)
                    .clip(CircleShape)
                    .background(color),
            )
        }
    }
}
