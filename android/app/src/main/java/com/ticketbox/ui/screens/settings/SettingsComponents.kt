package com.ticketbox.ui.screens.settings

import android.graphics.BitmapFactory
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.ui.draw.shadow
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
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.SettingsEntryCard
import com.ticketbox.ui.components.SoftPanel
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.AppElevation
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.ThemeVisuals
import com.ticketbox.ui.design.themeVisualsForSkin
import com.ticketbox.ui.theme.TicketboxAtmosphereBackground
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun SettingsEntryRow(
    title: String,
    subtitle: String,
    icon: ImageVector,
    onClick: () -> Unit,
) {
    SettingsEntryCard(
        title = title,
        subtitle = subtitle,
        icon = icon,
        onClick = onClick,
    )
}

@Composable
internal fun SettingsPageFrame(
    title: String,
    subtitle: String,
    onBack: (() -> Unit)?,
    content: @Composable () -> Unit,
) {
    val isSecondaryPage = onBack != null
    BackHandler(enabled = onBack != null) {
        onBack?.invoke()
    }

    AppPageScrollableColumn(
        role = AppPageRole.Settings,
    ) {
        Column(
            verticalArrangement = Arrangement.spacedBy(if (isSecondaryPage) 8.dp else 0.dp),
        ) {
            onBack?.let {
                TextButton(onClick = it) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("返回设置")
                }
            }
            AppPageHeader(title = title, subtitle = subtitle)
        }
        content()
    }
}

@Composable
internal fun BackgroundActionButton(
    text: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    leadingIcon: ImageVector? = null,
    onClick: () -> Unit,
) {
    QuietOutlinedButton(
        text = text,
        modifier = modifier,
        enabled = enabled,
        leadingIcon = leadingIcon,
        onClick = onClick,
    )
}

@Composable
internal fun AccountStatusCard(
    serverSettings: ServerSettings?,
    accountName: String? = null,
    ledgerName: String? = null,
    deviceName: String? = null,
    role: String? = null,
    lastUploadAt: String?,
    lastSyncAt: String?,
    busy: Boolean = false,
    onCheckConnection: (() -> Unit)? = null,
    onSync: (() -> Unit)? = null,
) {
    val displayAccount = serverSettings?.accountName?.takeIf { it.isNotBlank() } ?: accountName?.takeIf { it.isNotBlank() } ?: "我"
    val displayLedger = serverSettings?.ledgerName?.takeIf { it.isNotBlank() } ?: ledgerName?.takeIf { it.isNotBlank() } ?: "我的小票夹"
    val displayDevice = serverSettings?.deviceName?.takeIf { it.isNotBlank() } ?: deviceName?.takeIf { it.isNotBlank() } ?: "当前设备"
    val displayRole = serverSettings?.role?.takeIf { it.isNotBlank() } ?: role?.takeIf { it.isNotBlank() } ?: "owner"
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
                        text = displayLedger,
                        style = MaterialTheme.typography.titleMedium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                StatusPill(connected = serverSettings != null)
            }
            AccountInfoLine(text = "当前账号：$displayAccount")
            AccountInfoLine(text = "当前设备：$displayDevice")
            AccountInfoLine(text = "角色：$displayRole")
            AccountInfoLine(
                text = "最近上传：${(lastUploadAt ?: serverSettings?.latestUploadAt)?.let { displayTime(it) } ?: "还没有上传"}",
            )
            AccountInfoLine(
                text = "最近更新：${lastSyncAt?.let { displayTime(it) } ?: "还没有更新"} · 存储正常",
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
                        Text("更新账本")
                    }
                }
            }
        }
    }
}

@Composable
internal fun AdvancedStatusCard(
    serverUrl: String?,
    diagnostics: ConnectionDiagnostics?,
    expanded: Boolean,
    onToggleExpanded: () -> Unit,
) {
    val title = diagnostics?.let {
        when {
            it.failedCount > 0 -> "发现 ${it.failedCount} 个问题"
            it.warningCount > 0 -> "可用，有 ${it.warningCount} 个提醒"
            else -> "连接检测正常"
        }
    } ?: "尚未运行检测"

    SoftPanel(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(
                text = "连接地址：${serverUrl?.takeIf { it.isNotBlank() } ?: "未绑定"}",
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
internal fun StatusPill(connected: Boolean) {
    val visuals = LocalThemeVisuals.current
    val background = if (connected) visuals.chipSelected.copy(alpha = 0.78f) else visuals.chipUnselected.copy(alpha = 0.86f)
    val content = if (connected) visuals.primary else MaterialTheme.colorScheme.onSurfaceVariant
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
internal fun AccountInfoLine(text: String) {
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
internal fun BuiltInBackgroundCard(
    modifier: Modifier = Modifier,
    background: BuiltInBackground,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val skin = background.preferredSkin ?: AppSkin.Default
    val scheme = colorSchemeForSkin(skin)
    val visuals = themeVisualsForSkin(skin)
    val cardShape = RoundedCornerShape(AppRadius.large)
    val containerColor = if (selected) {
        visuals.glassTint.copy(alpha = 0.88f)
    } else {
        visuals.solidCard.copy(alpha = 0.94f)
    }
    val borderColor = if (selected) {
        visuals.primary.copy(alpha = 0.72f)
    } else {
        Color.White.copy(alpha = 0.54f)
    }

    Box(
        modifier = modifier
            .height(184.dp)
            .shadow(
                elevation = if (selected) AppElevation.softCardShadow else 7.dp,
                shape = cardShape,
                clip = false,
                ambientColor = visuals.shadowTint.copy(alpha = if (selected) 0.18f else 0.08f),
                spotColor = visuals.shadowTint.copy(alpha = if (selected) 0.14f else 0.06f),
            )
            .clip(cardShape)
            .background(containerColor)
            .border(width = 1.dp, color = borderColor, shape = cardShape)
            .clickable(onClick = onClick),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(10.dp),
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            GradientPreview(
                colors = background.gradientColors,
                scheme = scheme,
                visuals = visuals,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(100.dp),
            )
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = background.name,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 1,
                    )
                    if (selected) {
                        SkinPill(text = "当前", scheme = scheme, visuals = visuals, emphasized = true)
                    } else if (skin == AppSkin.Harbor) {
                        SkinPill(text = "推荐", scheme = scheme, visuals = visuals, emphasized = false)
                    }
                }
                Text(
                    text = "${background.category.displayName} · ${skin.displayName} · ${background.description}",
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
internal fun GradientPreview(
    colors: List<Long>,
    scheme: ColorScheme,
    visuals: ThemeVisuals,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(18.dp))
            .background(Brush.linearGradient(colors.map { Color(it) }))
            .padding(10.dp),
    ) {
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .size(82.dp)
                .background(
                    Brush.radialGradient(
                        listOf(visuals.heroGlow.copy(alpha = 0.42f), Color.Transparent),
                    ),
                ),
        )
        Box(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(42.dp)
                .background(
                    Brush.verticalGradient(
                        listOf(
                            Color.Transparent,
                            visuals.coolMist.copy(alpha = 0.24f),
                            Color.White.copy(alpha = 0.34f),
                        ),
                    ),
                ),
        )
        Box(
            modifier = Modifier
                .align(Alignment.TopStart)
                .fillMaxWidth(0.78f)
                .height(48.dp)
                .clip(RoundedCornerShape(14.dp))
                .background(
                    Brush.linearGradient(
                        listOf(
                            visuals.heroGradientStart.copy(alpha = 0.92f),
                            visuals.heroGradientEnd.copy(alpha = 0.88f),
                        ),
                    ),
                )
                .border(
                    width = 1.dp,
                    color = Color.White.copy(alpha = 0.24f),
                    shape = RoundedCornerShape(14.dp),
                )
                .padding(horizontal = 9.dp, vertical = 8.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                PreviewBar(width = 36.dp, color = scheme.onPrimary.copy(alpha = 0.70f))
                PreviewBar(width = 58.dp, color = scheme.onPrimary.copy(alpha = 0.90f))
            }
            Box(
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .width(28.dp)
                    .height(11.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(Color.White.copy(alpha = 0.78f)),
            )
        }
        Box(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .fillMaxWidth(0.70f)
                .height(30.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(visuals.glassTint.copy(alpha = 0.70f))
                .border(
                    width = 1.dp,
                    color = Color.White.copy(alpha = 0.32f),
                    shape = RoundedCornerShape(12.dp),
                )
                .padding(horizontal = 8.dp, vertical = 6.dp),
        ) {
            PreviewBar(width = 42.dp, color = visuals.primaryDark.copy(alpha = 0.38f))
            Box(
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .width(24.dp)
                    .height(8.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(visuals.chipSelected.copy(alpha = 0.86f)),
            )
        }
    }
}

@Composable
internal fun ImmersionModePicker(
    selected: ImmersionMode,
    onSelect: (ImmersionMode) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ImmersionMode.entries.forEach { mode ->
                AppFilterChip(
                    modifier = Modifier.weight(1f),
                    selected = selected == mode,
                    onClick = { onSelect(mode) },
                    label = mode.displayName,
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
internal fun BackgroundSwitchLine(
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
internal fun ThemeMoodPreview(
    settings: BackgroundSettings,
    skin: AppSkin,
) {
    val scheme = colorSchemeForSkin(skin)
    val visuals = themeVisualsForSkin(skin)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(132.dp)
            .clip(RoundedCornerShape(24.dp)),
    ) {
        TicketboxBackgroundLayer(settings = settings, skin = skin, surfaceRole = SurfaceRole.Pending)
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(resolveGlobalScrim(settings, skin, SurfaceRole.Pending)),
        )
        Box(
            modifier = Modifier
                .align(Alignment.Center)
                .fillMaxWidth(0.88f)
                .height(88.dp)
                .clip(RoundedCornerShape(22.dp))
                .background(
                    Brush.linearGradient(
                        visuals.heroGradient,
                    ),
                )
                .border(
                    width = 1.dp,
                    color = scheme.onPrimary.copy(alpha = 0.22f),
                    shape = RoundedCornerShape(22.dp),
                )
                .padding(14.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text(
                    text = "背景只参与氛围",
                    color = scheme.onPrimary.copy(alpha = 0.78f),
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    text = skin.displayName,
                    color = scheme.onPrimary,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Black,
                )
            }
            Box(
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .clip(RoundedCornerShape(18.dp))
                    .background(visuals.glassTint.copy(alpha = 0.84f))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(
                    text = settings.immersionMode.displayName,
                    color = visuals.primary,
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Black,
                )
            }
        }
    }
}

@Composable
internal fun CropSafeZones() {
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
internal fun ColumnScope.SafeZoneBand(
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
internal fun PreviewRoleCard(
    title: String,
    role: SurfaceRole,
    settings: BackgroundSettings,
    skin: AppSkin,
    content: @Composable () -> Unit,
) {
    val visuals = themeVisualsForSkin(skin)
    val outerShape = RoundedCornerShape(AppRadius.large)
    val innerShape = RoundedCornerShape(AppRadius.medium)
    val contentAlpha = resolveCardContainerAlpha(settings.immersionMode, role)
    val contentContainerColor = when (role) {
        SurfaceRole.Pending,
        SurfaceRole.Stats -> visuals.glassTint.copy(alpha = contentAlpha)
        SurfaceRole.Ledger,
        SurfaceRole.Edit,
        SurfaceRole.Settings,
        SurfaceRole.Auth -> visuals.solidCard.copy(alpha = contentAlpha)
    }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
        )
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(178.dp)
                .shadow(
                    elevation = 8.dp,
                    shape = outerShape,
                    clip = false,
                    ambientColor = visuals.shadowTint.copy(alpha = 0.08f),
                    spotColor = visuals.shadowTint.copy(alpha = 0.06f),
                )
                .clip(outerShape)
                .border(
                    width = 1.dp,
                    color = Color.White.copy(alpha = 0.30f),
                    shape = outerShape,
                ),
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
                        .fillMaxWidth()
                        .clip(innerShape)
                        .background(contentContainerColor)
                        .border(
                            width = 1.dp,
                            color = Color.White.copy(alpha = 0.32f),
                            shape = innerShape,
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
internal fun PreviewReceipt(
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
internal fun rememberLocalImage(path: String): ImageBitmap? {
    var image by remember(path) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(path) {
        image = withContext(Dispatchers.IO) {
            BitmapFactory.decodeFile(path)?.asImageBitmap()
        }
    }
    return image
}

@Composable
internal fun CategoryRuleCard(
    rule: CategoryRule,
    onToggleRule: (CategoryRule) -> Unit,
    onEditRule: () -> Unit,
    onDeleteRule: () -> Unit,
) {
    SoftPanel(containerAlpha = 0.98f) {
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

internal fun categoryRuleSummary(rules: List<CategoryRule>): String {
    val enabled = rules.count { it.enabled }
    return if (rules.isEmpty()) {
        "暂无规则"
    } else {
        "$enabled 条启用 · 共 ${rules.size} 条"
    }
}

@Composable
internal fun SkinOptionCard(
    modifier: Modifier = Modifier,
    skin: AppSkin,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val scheme = colorSchemeForSkin(skin)
    val visuals = themeVisualsForSkin(skin)
    val containerColor = if (selected) {
        visuals.glassTint.copy(alpha = 0.86f)
    } else {
        visuals.solidCard.copy(alpha = 0.94f)
    }
    val borderColor = if (selected) visuals.primary else Color.White.copy(alpha = 0.58f)
    val cardShape = RoundedCornerShape(AppRadius.large)

    Box(
        modifier = modifier
            .height(168.dp)
            .shadow(
                elevation = if (selected) AppElevation.softCardShadow else 6.dp,
                shape = cardShape,
                clip = false,
                ambientColor = visuals.shadowTint.copy(alpha = if (selected) 0.18f else 0.08f),
                spotColor = visuals.shadowTint.copy(alpha = if (selected) 0.14f else 0.06f),
            )
            .clip(cardShape)
            .background(containerColor)
            .border(width = 1.dp, color = borderColor, shape = cardShape)
            .clickable(onClick = onClick),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(10.dp),
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            SkinPreview(skin = skin, scheme = scheme, visuals = visuals)
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
                        SkinPill(text = "当前", scheme = scheme, visuals = visuals, emphasized = true)
                    } else if (skin == AppSkin.Harbor) {
                        SkinPill(text = "推荐", scheme = scheme, visuals = visuals, emphasized = false)
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
internal fun SkinPreview(skin: AppSkin, scheme: ColorScheme, visuals: ThemeVisuals) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(92.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(scheme.background),
    ) {
        TicketboxAtmosphereBackground(skin = skin)
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp)
                    .clip(RoundedCornerShape(15.dp))
                    .background(
                        Brush.linearGradient(
                            visuals.heroGradient,
                        ),
                    )
                    .padding(8.dp),
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    PreviewBar(width = 42.dp, color = scheme.onPrimary.copy(alpha = 0.80f))
                    PreviewBar(width = 64.dp, color = scheme.onPrimary.copy(alpha = 0.96f))
                }
                Box(
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .width(36.dp)
                        .height(18.dp)
                        .clip(RoundedCornerShape(999.dp))
                        .background(Color.White.copy(alpha = 0.82f)),
                )
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(24.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(visuals.glassTint.copy(alpha = 0.88f))
                    .padding(horizontal = 8.dp, vertical = 6.dp),
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    PreviewBar(width = 34.dp, color = visuals.primary.copy(alpha = 0.28f))
                    PreviewBar(width = 24.dp, color = visuals.accent.copy(alpha = 0.22f))
                }
            }
        }
    }
}

@Composable
internal fun PreviewBar(
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
internal fun SkinPill(
    text: String,
    scheme: ColorScheme,
    visuals: ThemeVisuals,
    emphasized: Boolean,
) {
    val background = if (emphasized) visuals.primary else visuals.chipSelected.copy(alpha = 0.86f)
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
