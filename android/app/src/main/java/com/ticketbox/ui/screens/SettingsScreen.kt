package com.ticketbox.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Security
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.res.integerResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.ScreenHeader
import com.ticketbox.ui.components.SoftPanel
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    state: SettingsUiState,
    currentSkin: AppSkin,
    onTestConnection: () -> Unit,
    onRunDiagnostics: () -> Unit,
    onRefreshServerSettings: () -> Unit,
    onSync: () -> Unit,
    onClearCache: () -> Unit,
    onSaveMonthlyBudget: (Long?) -> Unit,
    onCreateRule: (String, String, Int) -> Unit,
    onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    onToggleRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
    onSkinChange: (AppSkin) -> Unit,
    onBindingCleared: () -> Unit,
    showAdvancedTools: Boolean = false,
) {
    var budgetInput by remember(state.monthlyBudgetCents) {
        mutableStateOf(formatAmountInput(state.monthlyBudgetCents))
    }
    var localMessage by remember { mutableStateOf<String?>(null) }
    var showClearCacheDialog by remember { mutableStateOf(false) }
    var showClearBindingDialog by remember { mutableStateOf(false) }
    var showCategoryRules by remember { mutableStateOf(false) }
    var showDiagnosticsDetails by remember { mutableStateOf(false) }
    val appVersionName = stringResource(R.string.app_version_name)
    val appVersionCode = integerResource(R.integer.app_version_code)

    if (showCategoryRules) {
        ModalBottomSheet(onDismissRequest = { showCategoryRules = false }) {
            CategoryRulesSheet(
                rules = state.categoryRules,
                busy = state.busy,
                onCreateRule = onCreateRule,
                onUpdateRule = onUpdateRule,
                onToggleRule = onToggleRule,
                onDeleteRule = onDeleteRule,
                onClose = { showCategoryRules = false },
            )
        }
    }

    if (showClearCacheDialog) {
        AlertDialog(
            onDismissRequest = { showClearCacheDialog = false },
            title = { Text("清除手机本地数据？") },
            text = {
                Text("清除后，手机里已缓存的账单会移除。服务端账单不会删除，之后可以重新同步。")
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        showClearCacheDialog = false
                        onClearCache()
                    },
                ) {
                    Text("确定清除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { showClearCacheDialog = false }) {
                    Text("取消")
                }
            },
        )
    }

    if (showClearBindingDialog) {
        AlertDialog(
            onDismissRequest = { showClearBindingDialog = false },
            title = { Text("退出当前账本？") },
            text = {
                Text("退出后需要重新绑定小票夹。手机本地口令会被清除，服务端账单不会删除。")
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        showClearBindingDialog = false
                        onBindingCleared()
                    },
                ) {
                    Text("确定退出", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { showClearBindingDialog = false }) {
                    Text("取消")
                }
            },
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp)
            .padding(top = 8.dp, bottom = 96.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        ScreenHeader(
            title = "设置",
            subtitle = "账本状态、外观和本机数据。",
        )

        AccountStatusCard(
            serverSettings = state.serverSettings,
            lastUploadAt = state.lastUploadAt,
            lastSyncAt = state.lastConfirmedSyncAt,
            busy = state.busy,
            onCheckConnection = onTestConnection,
            onSync = onSync,
            onRefresh = onRefreshServerSettings,
        )

        if (showAdvancedTools) {
            SettingSection(title = "内部工具") {
                Text(
                    text = "仅内部版显示，用于服务拥有者联调和排障；灰度用户版不会出现这些信息。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !state.busy,
                        onClick = onRunDiagnostics,
                    ) {
                        Text("运行诊断")
                    }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !state.busy,
                        onClick = onRefreshServerSettings,
                    ) {
                        Text("刷新服务")
                    }
                }
                AdvancedStatusCard(
                    serverUrl = state.serverUrl,
                    diagnostics = state.diagnostics,
                    expanded = showDiagnosticsDetails,
                    onToggleExpanded = { showDiagnosticsDetails = !showDiagnosticsDetails },
                )
            }
        }

        SettingSection(title = "外观") {
            Text(
                text = "港湾是默认主题。背景会自动加遮罩，保证金额和账单文字清晰。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
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

        SettingSection(title = "预算") {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.72f),
                ),
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                            Text("月度预算", style = MaterialTheme.typography.titleSmall)
                            Text(
                                text = state.monthlyBudgetCents?.let { formatAmount(it) } ?: "未设置",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        Text(
                            text = "统计页显示进度",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    OutlinedTextField(
                        value = budgetInput,
                        onValueChange = { budgetInput = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("预算，单位元") },
                        placeholder = { Text("3000") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Button(
                            modifier = Modifier.weight(1f),
                            onClick = {
                                val amount = parseAmountCents(budgetInput)
                                if (budgetInput.isNotBlank() && (amount == null || amount <= 0L)) {
                                    localMessage = "请输入大于 0 的预算金额。"
                                    return@Button
                                }
                                localMessage = null
                                onSaveMonthlyBudget(amount)
                            },
                        ) {
                            Text("保存预算")
                        }
                        OutlinedButton(
                            modifier = Modifier.weight(1f),
                            enabled = state.monthlyBudgetCents != null || budgetInput.isNotBlank(),
                            onClick = {
                                budgetInput = ""
                                localMessage = null
                                onSaveMonthlyBudget(null)
                            },
                        ) {
                            Text("关闭预算")
                        }
                    }
                }
            }
        }

        SettingSection(title = "自动整理") {
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
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                            Text("商家分类规则", style = MaterialTheme.typography.titleSmall)
                            Text(
                                text = categoryRuleSummary(state.categoryRules),
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        OutlinedButton(onClick = { showCategoryRules = true }) {
                            Text("管理")
                        }
                    }
                    Text(
                        text = "自动识别只会填草稿，最终仍然由你确认入账。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }

        SettingSection(title = "数据与安全") {
            Text(
                text = "这些操作只影响当前手机，不会删除小票夹服务里的账单。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    onClick = { showClearCacheDialog = true },
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Icon(Icons.Filled.DeleteOutline, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("清除数据")
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    onClick = { showClearBindingDialog = true },
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("退出账本")
                }
            }
        }

        state.message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
        localMessage?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }

        SettingSection(title = "关于") {
            SoftPanel {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("小票夹", style = MaterialTheme.typography.titleSmall)
                    Text(
                        text = "版本 $appVersionName ($appVersionCode)",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = "私人截图确认账本。截图上传后不会自动入账，需要你确认后才会记录。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun AccountStatusCard(
    serverSettings: ServerSettings?,
    lastUploadAt: String?,
    lastSyncAt: String?,
    busy: Boolean,
    onCheckConnection: () -> Unit,
    onSync: () -> Unit,
    onRefresh: () -> Unit,
) {
    val ledgerName = serverSettings?.tenantName?.takeIf { it.isNotBlank() } ?: "我的小票夹"
    SoftPanel(containerAlpha = 0.66f) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(9.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(3.dp),
                ) {
                    Text(
                        text = "当前账本",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelMedium,
                    )
                    Text(
                        text = ledgerName,
                        style = MaterialTheme.typography.titleMedium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                StatusPill(connected = serverSettings != null)
            }
            AccountInfoLine(
                text = "最近上传：${(lastUploadAt ?: serverSettings?.latestUploadAt)?.let { displayTime(it) } ?: "还没有上传"}",
            )
            AccountInfoLine(
                text = "最近同步：${lastSyncAt?.let { displayTime(it) } ?: "还没有同步"} · 存储正常",
            )
            Row(
                modifier = Modifier.padding(top = 2.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                QuietOutlinedButton(
                    text = if (busy) "处理中" else "检查连接",
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    onClick = onCheckConnection,
                )
                Button(
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    onClick = {
                        onSync()
                        onRefresh()
                    },
                ) {
                    Text("同步账本")
                }
            }
        }
    }
}

@Composable
private fun AdvancedStatusCard(
    serverUrl: String?,
    diagnostics: ConnectionDiagnostics?,
    expanded: Boolean,
    onToggleExpanded: () -> Unit,
) {
    val title = diagnostics?.let {
        when {
            it.failedCount > 0 -> "发现 ${it.failedCount} 个问题"
            it.warningCount > 0 -> "可用，有 ${it.warningCount} 个提醒"
            else -> "连接诊断正常"
        }
    } ?: "尚未运行诊断"

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
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(
                text = "绑定地址：${serverUrl?.takeIf { it.isNotBlank() } ?: "未绑定"}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            diagnostics?.let { result ->
                if (expanded) {
                    result.checks.forEach { check ->
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
                OutlinedButton(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = onToggleExpanded,
                ) {
                    Text(if (expanded) "收起详情" else "查看详情")
                }
            }
        }
    }
}

@Composable
private fun StatusPill(connected: Boolean) {
    val background = if (connected) MaterialTheme.colorScheme.primary.copy(alpha = 0.18f) else MaterialTheme.colorScheme.surfaceVariant
    val content = if (connected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(background)
            .padding(horizontal = 10.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Filled.CloudDone,
            contentDescription = null,
            tint = content,
            modifier = Modifier.size(16.dp),
        )
        Text(
            text = if (connected) "已连接" else "连接中",
            color = content,
            style = MaterialTheme.typography.labelMedium,
        )
    }
}

@Composable
private fun AccountInfoLine(text: String) {
    Text(
        text = text,
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
private fun CategoryRulesSheet(
    rules: List<CategoryRule>,
    busy: Boolean,
    onCreateRule: (String, String, Int) -> Unit,
    onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    onToggleRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
    onClose: () -> Unit,
) {
    var keyword by remember { mutableStateOf("") }
    var category by remember { mutableStateOf("") }
    var priorityText by remember { mutableStateOf("10") }
    var editingRule by remember { mutableStateOf<CategoryRule?>(null) }
    var deletingRule by remember { mutableStateOf<CategoryRule?>(null) }
    var localMessage by remember { mutableStateOf<String?>(null) }

    deletingRule?.let { rule ->
        AlertDialog(
            onDismissRequest = { deletingRule = null },
            title = { Text("删除这条规则？") },
            text = { Text("删除后，后续识别不再参考“${rule.keyword}”。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        deletingRule = null
                        onDeleteRule(rule)
                    },
                ) {
                    Text("删除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { deletingRule = null }) {
                    Text("取消")
                }
            },
        )
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text("分类规则", style = MaterialTheme.typography.headlineSmall)
                Text(categoryRuleSummary(rules), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            TextButton(onClick = onClose) {
                Text("完成")
            }
        }

        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.74f),
            ),
        ) {
            Column(
                modifier = Modifier.padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    text = if (editingRule == null) "新增规则" else "编辑规则",
                    style = MaterialTheme.typography.titleMedium,
                )
                OutlinedTextField(
                    value = keyword,
                    onValueChange = { keyword = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("商家关键词") },
                    placeholder = { Text("OpenAI") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = category,
                    onValueChange = { category = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("推荐分类") },
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
                    enabled = !busy,
                    onClick = {
                        val priority = priorityText.toIntOrNull()
                        if (keyword.isBlank() || category.isBlank()) {
                            localMessage = "请填写关键词和分类。"
                            return@Button
                        }
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
                    Text(if (busy) "处理中" else if (editingRule == null) "添加规则" else "保存规则")
                }
                if (editingRule != null) {
                    OutlinedButton(
                        modifier = Modifier.fillMaxWidth(),
                        onClick = {
                            keyword = ""
                            category = ""
                            priorityText = "10"
                            editingRule = null
                            localMessage = null
                        },
                    ) {
                        Text("取消编辑")
                    }
                }
                localMessage?.let {
                    Text(it, color = MaterialTheme.colorScheme.secondary)
                }
            }
        }

        if (rules.isEmpty()) {
            Text(
                text = "暂无分类规则。添加后，自动识别会优先参考这些关键词。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            rules.forEach { rule ->
                CategoryRuleCard(
                    rule = rule,
                    onToggleRule = onToggleRule,
                    onEditRule = {
                        editingRule = rule
                        keyword = rule.keyword
                        category = rule.category
                        priorityText = rule.priority.toString()
                        localMessage = null
                    },
                    onDeleteRule = { deletingRule = rule },
                )
            }
        }
    }
}

@Composable
private fun CategoryRuleCard(
    rule: CategoryRule,
    onToggleRule: (CategoryRule) -> Unit,
    onEditRule: () -> Unit,
    onDeleteRule: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.72f),
        ),
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
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
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { onToggleRule(rule) }) {
                    Text(if (rule.enabled) "停用" else "启用")
                }
                OutlinedButton(onClick = onEditRule) {
                    Text("编辑")
                }
                OutlinedButton(onClick = onDeleteRule) {
                    Text("删除")
                }
            }
        }
    }
}

private fun categoryRuleSummary(rules: List<CategoryRule>): String {
    val enabled = rules.count { it.enabled }
    return if (rules.isEmpty()) {
        "暂无规则"
    } else {
        "$enabled 条启用 · 共 ${rules.size} 条"
    }
}

@Composable
private fun SettingSection(
    title: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = if (title == "外观") Icons.Filled.Palette else Icons.Filled.Security,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(18.dp),
            )
            Text(title, style = MaterialTheme.typography.titleMedium)
        }
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
        modifier = modifier.height(142.dp),
        onClick = onClick,
        colors = CardDefaults.cardColors(containerColor = containerColor),
        border = BorderStroke(1.dp, borderColor),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(10.dp),
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            SkinPreview(scheme = scheme)
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
                        SkinPill(text = "当前", scheme = scheme, emphasized = true)
                    } else if (skin == AppSkin.Harbor) {
                        SkinPill(text = "推荐", scheme = scheme, emphasized = false)
                    }
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = skin.description,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    SkinSwatches(scheme)
                }
            }
        }
    }
}

@Composable
private fun SkinPreview(scheme: ColorScheme) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(66.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(
                Brush.verticalGradient(
                    listOf(
                        scheme.background,
                        scheme.surfaceVariant,
                        scheme.surface,
                    ),
                ),
            )
            .padding(8.dp),
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    PreviewBar(width = 48.dp, color = scheme.onBackground.copy(alpha = 0.76f))
                    PreviewBar(width = 34.dp, color = scheme.onSurfaceVariant.copy(alpha = 0.64f))
                }
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(999.dp))
                        .background(scheme.primary)
                        .padding(horizontal = 7.dp, vertical = 3.dp),
                ) {
                    Text(
                        text = "¥36.80",
                        color = scheme.onPrimary,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(25.dp)
                    .clip(RoundedCornerShape(11.dp))
                    .background(scheme.surface.copy(alpha = 0.90f))
                    .padding(horizontal = 8.dp, vertical = 6.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        PreviewBar(width = 46.dp, color = scheme.onSurface.copy(alpha = 0.80f))
                        PreviewBar(width = 26.dp, color = scheme.onSurfaceVariant.copy(alpha = 0.68f))
                    }
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(999.dp))
                            .background(scheme.secondary.copy(alpha = 0.92f))
                            .padding(horizontal = 7.dp, vertical = 3.dp),
                    ) {
                        Text(
                            text = "餐饮",
                            color = scheme.onSecondary,
                            style = MaterialTheme.typography.labelSmall,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun PreviewBar(
    width: androidx.compose.ui.unit.Dp,
    color: androidx.compose.ui.graphics.Color,
) {
    Box(
        modifier = Modifier
            .width(width)
            .height(5.dp)
            .clip(RoundedCornerShape(999.dp))
            .background(color),
    )
}

@Composable
private fun SkinPill(
    text: String,
    scheme: ColorScheme,
    emphasized: Boolean,
) {
    val background = if (emphasized) scheme.primary else scheme.surfaceVariant.copy(alpha = 0.80f)
    val content = if (emphasized) scheme.onPrimary else scheme.onSurfaceVariant

    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(background)
            .padding(horizontal = 7.dp, vertical = 3.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (emphasized) {
            Icon(
                imageVector = Icons.Filled.Check,
                contentDescription = null,
                tint = content,
                modifier = Modifier.size(12.dp),
            )
        }
        Text(text = text, color = content, style = MaterialTheme.typography.labelSmall)
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
                    .size(12.dp)
                    .clip(CircleShape)
                    .background(color),
            )
        }
    }
}
