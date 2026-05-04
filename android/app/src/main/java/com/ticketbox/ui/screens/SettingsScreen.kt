package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.ui.components.formatStorageSize
import com.ticketbox.viewmodel.SettingsUiState

@Composable
fun SettingsScreen(
    state: SettingsUiState,
    onTestConnection: () -> Unit,
    onRefreshServerSettings: () -> Unit,
    onSync: () -> Unit,
    onClearCache: () -> Unit,
    onCreateRule: (String, String, Int) -> Unit,
    onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    onToggleRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
    onBindingCleared: () -> Unit,
) {
    var keyword by remember { mutableStateOf("") }
    var category by remember { mutableStateOf("") }
    var priorityText by remember { mutableStateOf("10") }
    var editingRule by remember { mutableStateOf<CategoryRule?>(null) }
    var localMessage by remember { mutableStateOf<String?>(null) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("设置", style = MaterialTheme.typography.headlineSmall)
        Text(
            text = "当前服务器：${state.serverUrl ?: "未绑定"}",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = "小票夹是私人半自动账本。截图上传后不会自动入账，需要你确认后才会记录。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = onTestConnection,
        ) {
            Text(if (state.busy) "处理中" else "测试连接")
        }
        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = onSync,
        ) {
            Text("重新同步")
        }
        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = onClearCache,
        ) {
            Text("清除本地缓存")
        }

        Text("服务器状态", style = MaterialTheme.typography.titleMedium)
        state.serverSettings?.let { serverSettings ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("上传限制：${serverSettings.maxUploadSizeMb} MB")
                    Text("缩略图：${if (serverSettings.generateThumbnail) "已启用" else "未启用"}")
                    Text(
                        "确认后删原图：${if (serverSettings.deleteImageAfterConfirm) "已启用" else "未启用"}",
                    )
                    Text("保留天数：${serverSettings.deleteImageAfterDays}")
                    Text("OCR：${serverSettings.ocrProvider}")
                    Text(
                        "账单：待确认 ${serverSettings.pendingCount} · 已确认 ${serverSettings.confirmedCount} · 已拒绝 ${serverSettings.rejectedCount}",
                    )
                    Text("疑似重复：${serverSettings.suspectedDuplicateCount}")
                    Text("图片占用：${formatStorageSize(serverSettings.uploadStorageBytes)}")
                }
            }
        } ?: Text("服务器状态未加载", color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = onRefreshServerSettings,
        ) {
            Text("刷新服务器状态")
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
