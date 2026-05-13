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
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.domain.model.ledgerScopeLabel
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
    val displayRole = ledgerRoleLabel(
        serverSettings?.role?.takeIf { it.isNotBlank() }
            ?: role?.takeIf { it.isNotBlank() }
            ?: "owner",
    )
    val ledgerScope = serverSettings?.ledgerIsDefault?.let { ledgerScopeLabel(it) }
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
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    ledgerScope?.let { AccountLedgerScopePill(text = it) }
                    StatusPill(connected = serverSettings != null)
                }
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
private fun AccountLedgerScopePill(text: String) {
    val visuals = LocalThemeVisuals.current
    Text(
        text = text,
        color = visuals.primary,
        style = MaterialTheme.typography.labelMedium,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(visuals.chipSelected.copy(alpha = 0.68f))
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
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
