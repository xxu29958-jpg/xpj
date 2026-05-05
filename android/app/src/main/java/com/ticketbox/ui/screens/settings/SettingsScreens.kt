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
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.FilterChip
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
import com.ticketbox.ui.components.SoftPanel
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
fun SettingsRootScreen(
    state: SettingsUiState,
    showAdvancedTools: Boolean,
    onOpenServer: () -> Unit,
    onOpenAppearance: () -> Unit,
    onOpenCategoryRules: () -> Unit,
    onOpenDataExport: () -> Unit,
    onOpenSecurity: () -> Unit,
    onOpenAbout: () -> Unit,
) {
    SettingsPageFrame(
        title = "设置",
        subtitle = "账本状态、外观和本机数据。",
        onBack = null,
    ) {
        AccountStatusCard(
            serverSettings = state.serverSettings,
            lastUploadAt = state.lastUploadAt,
            lastSyncAt = state.lastConfirmedSyncAt,
        )
        SettingsEntryRow(
            title = "服务器与联调",
            subtitle = if (showAdvancedTools) "连接测试、联调自检、同步状态" else "连接测试和同步状态",
            icon = Icons.Filled.CloudDone,
            onClick = onOpenServer,
        )
        SettingsEntryRow(
            title = "外观与主题",
            subtitle = "主题皮肤、自定义背景、沉浸强度",
            icon = Icons.Filled.Palette,
            onClick = onOpenAppearance,
        )
        SettingsEntryRow(
            title = "分类规则",
            subtitle = "商家关键词和自动分类建议",
            icon = Icons.Filled.Category,
            onClick = onOpenCategoryRules,
        )
        SettingsEntryRow(
            title = "数据与导出",
            subtitle = "月度预算、本地缓存、CSV 导出说明",
            icon = Icons.Filled.FileDownload,
            onClick = onOpenDataExport,
        )
        SettingsEntryRow(
            title = "安全与隐私",
            subtitle = "本机解锁、本地数据、退出账本",
            icon = Icons.Filled.Security,
            onClick = onOpenSecurity,
        )
        SettingsEntryRow(
            title = "关于",
            subtitle = "版本和产品边界",
            icon = Icons.Filled.Info,
            onClick = onOpenAbout,
        )
        state.message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
    }
}

@Composable
fun ServerSettingsScreen(
    state: SettingsUiState,
    showAdvancedTools: Boolean,
    onBack: () -> Unit,
    onTestConnection: () -> Unit,
    onRunDiagnostics: () -> Unit,
    onRefreshServerSettings: () -> Unit,
    onSync: () -> Unit,
) {
    var showDiagnosticsDetails by remember { mutableStateOf(false) }
    SettingsPageFrame(
        title = "服务器与联调",
        subtitle = "普通版只显示连接状态，内部版保留诊断明细。",
        onBack = onBack,
    ) {
        AccountStatusCard(
            serverSettings = state.serverSettings,
            lastUploadAt = state.lastUploadAt,
            lastSyncAt = state.lastConfirmedSyncAt,
            busy = state.busy,
            onCheckConnection = onTestConnection,
            onSync = {
                onSync()
                onRefreshServerSettings()
            },
        )
        if (showAdvancedTools) {
            SettingsSection(title = "内部工具", icon = Icons.Filled.Settings) {
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
        state.message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
    }
}

@Composable
fun AppearanceScreen(
    state: SettingsUiState,
    currentSkin: AppSkin,
    onBack: () -> Unit,
    onSkinChange: (AppSkin) -> Unit,
    onOpenGallery: () -> Unit,
    onPickCustomImage: () -> Unit,
    onPreviewThemeDefault: () -> Unit,
    onClearBackgroundImage: () -> Unit,
    onImmersionModeChange: (ImmersionMode) -> Unit,
    onParallaxChange: (Boolean) -> Unit,
    onReduceMotionChange: (Boolean) -> Unit,
) {
    SettingsPageFrame(
        title = "外观与主题",
        subtitle = "港湾作为默认推荐，背景参与氛围但不抢账单内容。",
        onBack = onBack,
    ) {
        SettingsSection(title = "主题皮肤", icon = Icons.Filled.Palette) {
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
        SettingsSection(title = "背景", icon = Icons.Filled.Image) {
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                            Text("当前背景", style = MaterialTheme.typography.titleSmall)
                            Text(
                                text = AppearanceDefaults.backgroundSourceLabel(state.backgroundSettings),
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        SkinPill(
                            text = state.backgroundSettings.immersionMode.displayName,
                            scheme = MaterialTheme.colorScheme,
                            emphasized = false,
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Button(
                            modifier = Modifier.weight(1f),
                            onClick = onOpenGallery,
                        ) {
                            Text("背景图库")
                        }
                        OutlinedButton(
                            modifier = Modifier.weight(1f),
                            onClick = onPickCustomImage,
                        ) {
                            Text("从相册选择")
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        OutlinedButton(
                            modifier = Modifier.weight(1f),
                            onClick = onPreviewThemeDefault,
                        ) {
                            Text("恢复主题默认")
                        }
                        OutlinedButton(
                            modifier = Modifier.weight(1f),
                            enabled = state.backgroundSettings.customImagePath != null,
                            onClick = onClearBackgroundImage,
                        ) {
                            Text("清除自定义图")
                        }
                    }
                }
            }
        }
        SettingsSection(title = "沉浸强度", icon = Icons.Filled.Tune) {
            ImmersionModePicker(
                selected = state.backgroundSettings.immersionMode,
                onSelect = onImmersionModeChange,
            )
            BackgroundSwitchLine(
                title = "视差动效",
                subtitle = "背景轻微参与层次变化",
                checked = state.backgroundSettings.enableParallax && !state.backgroundSettings.reduceMotion,
                enabled = !state.backgroundSettings.reduceMotion,
                onCheckedChange = onParallaxChange,
            )
            BackgroundSwitchLine(
                title = "减少动效",
                subtitle = "关闭背景动效，保持录入稳定",
                checked = state.backgroundSettings.reduceMotion,
                enabled = true,
                onCheckedChange = onReduceMotionChange,
            )
        }
        state.message?.let {
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
    }
}

@Composable
fun BackgroundGalleryScreen(
    currentSettings: BackgroundSettings,
    onBack: () -> Unit,
    onPickCustomImage: () -> Unit,
    onPreviewThemeDefault: () -> Unit,
    onPreviewBuiltIn: (BuiltInBackground) -> Unit,
) {
    var selectedCategory by remember { mutableStateOf<BuiltInBackgroundCategory?>(null) }
    val backgrounds = selectedCategory?.let(BackgroundCatalog::byCategory) ?: BackgroundCatalog.entries
    SettingsPageFrame(
        title = "背景图库",
        subtitle = "点击后先预览，确认应用后才会保存。",
        onBack = onBack,
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            FilterChip(
                selected = selectedCategory == null,
                onClick = { selectedCategory = null },
                label = { Text("推荐") },
            )
            BuiltInBackgroundCategory.entries.forEach { category ->
                FilterChip(
                    selected = selectedCategory == category,
                    onClick = { selectedCategory = category },
                    label = { Text(category.displayName) },
                )
            }
        }
        backgrounds.chunked(2).forEach { rowBackgrounds ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                rowBackgrounds.forEach { background ->
                    BuiltInBackgroundCard(
                        modifier = Modifier.weight(1f),
                        background = background,
                        selected = currentSettings.builtInBackgroundId == background.id,
                        onClick = { onPreviewBuiltIn(background) },
                    )
                }
                if (rowBackgrounds.size == 1) {
                    Spacer(modifier = Modifier.weight(1f))
                }
            }
        }
        SettingsSection(title = "自定义", icon = Icons.Filled.PhotoLibrary) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(
                    modifier = Modifier.weight(1f),
                    onClick = onPickCustomImage,
                ) {
                    Text("从相册选择")
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    onClick = onPreviewThemeDefault,
                ) {
                    Text("主题默认")
                }
            }
        }
    }
}

@Composable
fun BackgroundCropScreen(
    sourcePath: String,
    onBack: () -> Unit,
    onComplete: (BackgroundCropMode) -> Unit,
) {
    var cropMode by remember { mutableStateOf(BackgroundCropMode.Center) }
    SettingsPageFrame(
        title = "调整背景",
        subtitle = "避开顶部标题和底部导航区域，保证账单内容清晰可读。",
        onBack = onBack,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(9f / 16f)
                .clip(RoundedCornerShape(28.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
        ) {
            val bitmap = rememberLocalImage(sourcePath)
            if (bitmap != null) {
                Image(
                    bitmap = bitmap,
                    contentDescription = null,
                    modifier = Modifier.fillMaxSize(),
                    contentScale = ContentScale.Crop,
                    alignment = when (cropMode) {
                        BackgroundCropMode.Top -> Alignment.TopCenter
                        BackgroundCropMode.Center -> Alignment.Center
                        BackgroundCropMode.Bottom -> Alignment.BottomCenter
                    },
                )
            }
            CropSafeZones()
        }
        SettingsSection(title = "构图位置", icon = Icons.Filled.Tune) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                BackgroundCropMode.entries.forEach { mode ->
                    FilterChip(
                        modifier = Modifier.weight(1f),
                        selected = cropMode == mode,
                        onClick = { cropMode = mode },
                        label = { Text(mode.displayName) },
                    )
                }
            }
            Text(
                text = cropMode.description,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(
                modifier = Modifier.weight(1f),
                onClick = onBack,
            ) {
                Text("取消")
            }
            Button(
                modifier = Modifier.weight(1f),
                onClick = { onComplete(cropMode) },
            ) {
                Text("完成，去预览")
            }
        }
    }
}

@Composable
fun BackgroundPreviewScreen(
    initialSettings: BackgroundSettings,
    currentSkin: AppSkin,
    title: String,
    onBack: () -> Unit,
    onApply: (BackgroundSettings) -> Unit,
) {
    var previewSettings by remember(initialSettings) { mutableStateOf(initialSettings) }
    SettingsPageFrame(
        title = "背景预览",
        subtitle = "$title · 只有点击应用才会保存",
        onBack = onBack,
    ) {
        ImmersionModePicker(
            selected = previewSettings.immersionMode,
            onSelect = { mode -> previewSettings = previewSettings.copy(immersionMode = mode) },
        )
        PreviewRoleCard(
            title = "待确认",
            role = SurfaceRole.Pending,
            settings = previewSettings,
            skin = currentSkin,
        ) {
            PreviewReceipt("美团外卖", "¥36.80", "餐饮 · 请核对")
            PreviewReceipt("建行提醒", "等待你确认金额", "识别建议")
        }
        PreviewRoleCard(
            title = "账本",
            role = SurfaceRole.Ledger,
            settings = previewSettings,
            skin = currentSkin,
        ) {
            PreviewReceipt("OpenAI", "¥200.00", "AI订阅 · 2026年5月")
            PreviewReceipt("美团外卖", "¥36.80", "餐饮 · 午饭")
        }
        PreviewRoleCard(
            title = "统计",
            role = SurfaceRole.Stats,
            settings = previewSettings,
            skin = currentSkin,
        ) {
            Text("本月支出 ¥4,286.90", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Black)
            Text("餐饮 42% · AI订阅 ¥200.00", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        PreviewRoleCard(
            title = "编辑确认",
            role = SurfaceRole.Edit,
            settings = previewSettings,
            skin = currentSkin,
        ) {
            PreviewReceipt("金额", "¥36.80", "商家 美团外卖 · 分类 餐饮")
            Button(modifier = Modifier.fillMaxWidth(), onClick = {}) {
                Text("确认入账")
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(
                modifier = Modifier.weight(1f),
                onClick = onBack,
            ) {
                Text("取消预览")
            }
            Button(
                modifier = Modifier.weight(1f),
                onClick = { onApply(previewSettings) },
            ) {
                Text("应用背景")
            }
        }
    }
}

@Composable
fun CategoryRulesScreen(
    rules: List<CategoryRule>,
    busy: Boolean,
    onBack: () -> Unit,
    onCreateRule: (String, String, Int) -> Unit,
    onUpdateRule: (CategoryRule, String, String, Int) -> Unit,
    onToggleRule: (CategoryRule) -> Unit,
    onDeleteRule: (CategoryRule) -> Unit,
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

    SettingsPageFrame(
        title = "分类规则",
        subtitle = categoryRuleSummary(rules),
        onBack = onBack,
    ) {
        SettingsSection(title = if (editingRule == null) "新增规则" else "编辑规则", icon = Icons.Filled.Category) {
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
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
fun DataExportScreen(
    state: SettingsUiState,
    onBack: () -> Unit,
    onSync: () -> Unit,
    onClearCache: () -> Unit,
    onSaveMonthlyBudget: (Long?) -> Unit,
) {
    var budgetInput by remember(state.monthlyBudgetCents) {
        mutableStateOf(formatAmountInput(state.monthlyBudgetCents))
    }
    var localMessage by remember { mutableStateOf<String?>(null) }
    var showClearCacheDialog by remember { mutableStateOf(false) }

    if (showClearCacheDialog) {
        AlertDialog(
            onDismissRequest = { showClearCacheDialog = false },
            title = { Text("清除手机本地数据？") },
            text = { Text("清除后，手机里已缓存的账单会移除。服务端账单不会删除，之后可以重新同步。") },
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

    SettingsPageFrame(
        title = "数据与导出",
        subtitle = "本地缓存只保存在手机，CSV 导出在账本页发起。",
        onBack = onBack,
    ) {
        SettingsSection(title = "月度预算", icon = Icons.Filled.FileDownload) {
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        text = state.monthlyBudgetCents?.let { "当前预算 ${formatAmount(it)}" } ?: "未设置预算",
                        style = MaterialTheme.typography.titleSmall,
                    )
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
        SettingsSection(title = "同步与缓存", icon = Icons.Filled.RestartAlt) {
            Text(
                text = "已确认账单会缓存在手机，离线时账本页仍可查看本地记录。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(
                    modifier = Modifier.weight(1f),
                    enabled = !state.busy,
                    onClick = onSync,
                ) {
                    Text(if (state.busy) "同步中" else "重新同步")
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    onClick = { showClearCacheDialog = true },
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Text("清除缓存")
                }
            }
            Text(
                text = "CSV 导出请在账本页选择月份和分类后点击导出账单；没有账单时按钮会禁用。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        state.message?.let { Text(it, color = MaterialTheme.colorScheme.secondary) }
        localMessage?.let { Text(it, color = MaterialTheme.colorScheme.secondary) }
    }
}

@Composable
fun SecurityPrivacyScreen(
    onBack: () -> Unit,
    onClearCache: () -> Unit,
    onBindingCleared: () -> Unit,
) {
    var showClearCacheDialog by remember { mutableStateOf(false) }
    var showClearBindingDialog by remember { mutableStateOf(false) }

    if (showClearCacheDialog) {
        AlertDialog(
            onDismissRequest = { showClearCacheDialog = false },
            title = { Text("清除手机本地数据？") },
            text = { Text("服务端账单不会删除。之后可重新同步已入账账单。") },
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
            dismissButton = { TextButton(onClick = { showClearCacheDialog = false }) { Text("取消") } },
        )
    }
    if (showClearBindingDialog) {
        AlertDialog(
            onDismissRequest = { showClearBindingDialog = false },
            title = { Text("退出当前账本？") },
            text = { Text("退出后需要重新绑定小票夹。手机本地口令会被清除，服务端账单不会删除。") },
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
            dismissButton = { TextButton(onClick = { showClearBindingDialog = false }) { Text("取消") } },
        )
    }

    SettingsPageFrame(
        title = "安全与隐私",
        subtitle = "口令保存在本机安全区，背景图片不会上传。",
        onBack = onBack,
    ) {
        SettingsSection(title = "本机解锁", icon = Icons.Filled.Security) {
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("指纹 / 面容只用于本地解锁", style = MaterialTheme.typography.titleSmall)
                    Text(
                        text = "服务端访问仍然使用绑定时保存的访问口令。App 切到后台超过 5 分钟后会要求重新解锁。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = "自定义背景只保存在手机私有目录，不上传到小票夹服务。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        SettingsSection(title = "危险操作", icon = Icons.Filled.DeleteOutline) {
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
    }
}

@Composable
fun AboutScreen(
    appVersionName: String,
    appVersionCode: Int,
    onBack: () -> Unit,
) {
    SettingsPageFrame(
        title = "关于",
        subtitle = "小票夹是私人半自动账本。",
        onBack = onBack,
    ) {
        SoftPanel(containerAlpha = 0.96f) {
            Column(
                modifier = Modifier.padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("小票夹", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Black)
                Text(
                    text = "版本 $appVersionName ($appVersionCode)",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = "截图上传后不会自动入账，需要你确认后才会记录。OCR 只填草稿，重复检测只提示。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
fun SettingsEntryRow(
    title: String,
    subtitle: String,
    icon: ImageVector,
    onClick: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = onClick,
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.96f),
        ),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.46f)),
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(38.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
            }
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(3.dp),
            ) {
                Text(title, style = MaterialTheme.typography.titleSmall)
                Text(
                    text = subtitle,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text("进入", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelMedium)
        }
    }
}

@Composable
private fun SettingsPageFrame(
    title: String,
    subtitle: String,
    onBack: (() -> Unit)?,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp)
            .padding(top = 8.dp, bottom = 96.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        onBack?.let {
            TextButton(onClick = it) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(4.dp))
                Text("返回设置")
            }
        }
        ScreenHeader(title = title, subtitle = subtitle)
        content()
    }
}

@Composable
private fun AccountStatusCard(
    serverSettings: ServerSettings?,
    lastUploadAt: String?,
    lastSyncAt: String?,
    busy: Boolean = false,
    onCheckConnection: (() -> Unit)? = null,
    onSync: (() -> Unit)? = null,
) {
    val ledgerName = serverSettings?.tenantName?.takeIf { it.isNotBlank() } ?: "我的小票夹"
    SoftPanel(containerAlpha = 0.96f) {
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
            if (onCheckConnection != null && onSync != null) {
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
                        onClick = onSync,
                    ) {
                        Text("同步账本")
                    }
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
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.96f),
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
private fun BuiltInBackgroundCard(
    modifier: Modifier = Modifier,
    background: BuiltInBackground,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Card(
        modifier = modifier.height(164.dp),
        onClick = onClick,
        colors = CardDefaults.cardColors(
            containerColor = if (selected) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surface.copy(alpha = 0.96f)
            },
        ),
        border = BorderStroke(
            width = 1.dp,
            color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.48f),
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(10.dp),
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            GradientPreview(
                colors = background.gradientColors,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(84.dp),
            )
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(background.name, style = MaterialTheme.typography.titleSmall)
                    if (selected) {
                        Icon(Icons.Filled.Check, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
                    }
                }
                Text(
                    text = "${background.category.displayName} · ${background.preferredSkin?.displayName ?: "通用"}",
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
private fun GradientPreview(
    colors: List<Long>,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(18.dp))
            .background(Brush.verticalGradient(colors.map { Color(it) }))
            .padding(10.dp),
    ) {
        Box(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .fillMaxWidth(0.70f)
                .height(28.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(Color.White.copy(alpha = 0.62f)),
        )
    }
}

@Composable
private fun ImmersionModePicker(
    selected: ImmersionMode,
    onSelect: (ImmersionMode) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ImmersionMode.entries.forEach { mode ->
                FilterChip(
                    modifier = Modifier.weight(1f),
                    selected = selected == mode,
                    onClick = { onSelect(mode) },
                    label = {
                        Text(
                            text = mode.displayName,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    },
                )
            }
        }
        Text(
            text = selected.description,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun BackgroundSwitchLine(
    title: String,
    subtitle: String,
    checked: Boolean,
    enabled: Boolean,
    onCheckedChange: (Boolean) -> Unit,
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
            Text(title, style = MaterialTheme.typography.labelLarge)
            Text(
                text = subtitle,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Switch(
            checked = checked,
            enabled = enabled,
            onCheckedChange = onCheckedChange,
        )
    }
}

@Composable
private fun CropSafeZones() {
    Column(modifier = Modifier.fillMaxSize()) {
        SafeZoneBand("顶部标题区", 0.15f)
        Box(
            modifier = Modifier
                .weight(0.70f)
                .fillMaxWidth()
                .border(1.dp, Color.White.copy(alpha = 0.55f), RoundedCornerShape(18.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "主要阅读区",
                color = Color.White.copy(alpha = 0.82f),
                style = MaterialTheme.typography.labelMedium,
            )
        }
        SafeZoneBand("底部导航区", 0.15f)
    }
}

@Composable
private fun ColumnScope.SafeZoneBand(
    text: String,
    weight: Float,
) {
    Box(
        modifier = Modifier
            .weight(weight)
            .fillMaxWidth()
            .background(Color.Black.copy(alpha = 0.30f)),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = text, color = Color.White, style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
private fun PreviewRoleCard(
    title: String,
    role: SurfaceRole,
    settings: BackgroundSettings,
    skin: AppSkin,
    content: @Composable () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall)
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(178.dp)
                .clip(RoundedCornerShape(24.dp)),
        ) {
            TicketboxBackgroundLayer(settings = settings, skin = skin, surfaceRole = role)
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(resolveGlobalScrim(settings, skin, role)),
            )
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(18.dp))
                        .background(
                            MaterialTheme.colorScheme.surface.copy(
                                alpha = resolveCardContainerAlpha(settings.immersionMode, role),
                            ),
                        )
                        .padding(10.dp),
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        content()
                    }
                }
            }
        }
    }
}

@Composable
private fun PreviewReceipt(
    title: String,
    amount: String,
    subtitle: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(title, style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        }
        Text(amount, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Black)
    }
}

@Composable
private fun rememberLocalImage(path: String): ImageBitmap? {
    var image by remember(path) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(path) {
        image = withContext(Dispatchers.IO) {
            BitmapFactory.decodeFile(path)?.asImageBitmap()
        }
    }
    return image
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
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.96f),
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
        MaterialTheme.colorScheme.surface.copy(alpha = 0.96f)
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
            SkinPreview(skin = skin, scheme = scheme)
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
private fun SkinPreview(skin: AppSkin, scheme: ColorScheme) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(66.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(backgroundBrushForSkin(skin))
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
                    .background(scheme.surface.copy(alpha = 0.92f))
                    .padding(horizontal = 8.dp, vertical = 6.dp),
            )
        }
    }
}

@Composable
private fun PreviewBar(
    width: Dp,
    color: Color,
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
