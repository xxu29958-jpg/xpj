package com.ticketbox.ui.screens.settings

import android.graphics.BitmapFactory
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
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
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.RuleApplyPreviewItem
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.ui.appearance.AppearanceDefaults
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.appearance.BuiltInBackground
import com.ticketbox.ui.appearance.BuiltInBackgroundCategory
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.appearance.background.TicketboxBackgroundLayer
import com.ticketbox.ui.appearance.background.resolveCardContainerAlpha
import com.ticketbox.ui.appearance.background.resolveGlobalScrim
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.ScreenHeader
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.theme.backgroundBrushForSkin
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun CategoryRulesScreen(
    rules: List<CategoryRule>,
    busy: Boolean,
    readOnly: Boolean,
    onBack: () -> Unit,
    onCreateRule: (String, String, Int) -> Unit,
    onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    onToggleRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
    applications: List<RuleApplicationBatch>,
    confirmedPreview: RuleApplyConfirmedResult?,
    onPreviewApplyConfirmedRules: () -> Unit,
    onConfirmApplyConfirmedRules: () -> Unit,
    onRollbackRuleApplication: (RuleApplicationBatch) -> Unit,
) {
    var keyword by remember { mutableStateOf("") }
    var category by remember { mutableStateOf("") }
    var priorityText by remember { mutableStateOf("10") }
    var editingRule by remember { mutableStateOf<CategoryRule?>(null) }
    var deletingRule by remember { mutableStateOf<CategoryRule?>(null) }
    var rollbackApplication by remember { mutableStateOf<RuleApplicationBatch?>(null) }
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

    rollbackApplication?.let { application ->
        AlertDialog(
            onDismissRequest = { rollbackApplication = null },
            title = { Text("回退这次应用？") },
            text = { Text("会尽量恢复这次规则应用前的分类，已经手动改过的账单会跳过。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        rollbackApplication = null
                        onRollbackRuleApplication(application)
                    },
                ) {
                    Text("回退", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { rollbackApplication = null }) {
                    Text("取消")
                }
            },
        )
    }

    SettingsPageFrame(
        title = "分类规则",
        subtitle = categoryRuleSummary(rules),
        onBack = onBack,
    ) {
        if (!readOnly) {
            SettingsSection(title = if (editingRule == null) "新增规则" else "编辑规则", icon = Icons.Filled.Category) {
                AppGlassCard(containerAlpha = 0.96f) {
                    Column(
                        modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                    ) {
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
            }
        } else {
            Text(
                text = "当前角色为只读，无法修改账本。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        SettingsSection(title = "规则列表", icon = Icons.Filled.Category) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                if (rules.isEmpty()) {
                    Text(
                        text = "暂无分类规则。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    rules.forEach { rule ->
                        CategoryRuleCard(
                            rule = rule,
                            readOnly = readOnly,
                            onToggleRule = onToggleRule,
                            onEditRule = {
                                if (!readOnly) {
                                    editingRule = rule
                                    keyword = rule.keyword
                                    category = rule.category
                                    priorityText = rule.priority.toString()
                                    localMessage = null
                                }
                            },
                            onDeleteRule = { if (!readOnly) deletingRule = rule },
                        )
                    }
                }
            }
        }
        SettingsSection(title = "已入账应用", icon = Icons.Filled.RestartAlt) {
            ConfirmedRuleApplyPanel(
                preview = confirmedPreview,
                busy = busy,
                readOnly = readOnly,
                onPreview = onPreviewApplyConfirmedRules,
                onConfirm = onConfirmApplyConfirmedRules,
            )
        }
        SettingsSection(title = "最近应用记录", icon = Icons.Filled.RestartAlt) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                if (applications.isEmpty()) {
                    Text(
                        text = "暂无应用记录。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    applications.forEach { application ->
                        RuleApplicationCard(
                            application = application,
                            readOnly = readOnly,
                            busy = busy,
                            onRollback = { rollbackApplication = application },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ConfirmedRuleApplyPanel(
    preview: RuleApplyConfirmedResult?,
    busy: Boolean,
    readOnly: Boolean,
    onPreview: () -> Unit,
    onConfirm: () -> Unit,
) {
    AppGlassCard(containerAlpha = 0.98f) {
        Column(modifier = Modifier.padding(AppSpacing.compactGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Text(
                text = "先预览已入账账单中可被规则更新的分类，再手动确认应用。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            preview?.let { result ->
                Text(
                    text = "扫描 ${result.confirmedScanned} 笔 · 可更新 ${result.changedCount} 笔 · 未命中 ${result.noMatchCount} 笔",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (result.scanLimitReached) {
                    Text(
                        text = "本次只扫描前 ${result.scanLimit} 笔。",
                        color = MaterialTheme.colorScheme.secondary,
                    )
                }
                result.items.take(5).forEach { item ->
                    RuleApplyPreviewRow(item)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    enabled = !busy,
                    onClick = onPreview,
                ) {
                    Text(if (busy) "处理中" else "预览")
                }
                Button(
                    enabled = !busy && !readOnly && (preview?.changedCount ?: 0) > 0,
                    onClick = onConfirm,
                ) {
                    Text("确认应用")
                }
            }
            if (readOnly) {
                Text(
                    text = "当前角色为只读，不能应用到已入账账单。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun RuleApplyPreviewRow(item: RuleApplyPreviewItem) {
    AppGlassCard(containerAlpha = 0.82f) {
        Column(modifier = Modifier.padding(AppSpacing.compactPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(
                text = item.merchant?.takeIf { it.isNotBlank() } ?: "未填写商家",
                style = MaterialTheme.typography.labelLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = "${item.currentCategory} -> ${item.suggestedCategory} · ${item.ruleKeyword}",
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun RuleApplicationCard(
    application: RuleApplicationBatch,
    readOnly: Boolean,
    busy: Boolean,
    onRollback: () -> Unit,
) {
    AppGlassCard(containerAlpha = 0.98f) {
        Column(modifier = Modifier.padding(AppSpacing.compactGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = if (application.isRolledBack) "已回退" else "已应用",
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(
                    text = "${application.changedCount} 笔",
                    color = MaterialTheme.colorScheme.primary,
                    fontWeight = FontWeight.Bold,
                )
            }
            Text(
                text = "扫描 ${application.pendingScanned} 笔 · ${displayTime(application.createdAt)}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            application.rolledBackAt?.let {
                Text(
                    text = "回退时间：${displayTime(it)}",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (!readOnly && !application.isRolledBack) {
                OutlinedButton(
                    enabled = !busy,
                    onClick = onRollback,
                ) {
                    Text("回退")
                }
            }
        }
    }
}
