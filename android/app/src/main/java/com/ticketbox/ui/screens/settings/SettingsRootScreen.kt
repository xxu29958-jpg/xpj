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
import androidx.compose.material.icons.filled.FolderShared
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Notifications
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
import com.ticketbox.BuildConfig
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
    onOpenMerchantAliases: () -> Unit,
    onOpenDataExport: () -> Unit,
    onOpenNotifications: () -> Unit,
    onOpenSecurity: () -> Unit,
    onOpenLedgers: () -> Unit = {},
    onOpenFamilyMembers: () -> Unit = {},
    onOpenJoinFamilyLedger: () -> Unit = {},
    onOpenAbout: () -> Unit,
) {
    val connectionTitle = if (showAdvancedTools) "服务器与联调" else "账本连接"
    val connectionSubtitle = if (showAdvancedTools) {
        "连接测试、联调自检、同步状态"
    } else {
        "检查连接、更新账本状态"
    }
    SettingsPageFrame(
        title = "设置",
        subtitle = "账本状态、外观和本机数据。",
        onBack = null,
    ) {
        AccountStatusCard(
            serverSettings = state.serverSettings,
            accountName = state.accountName,
            ledgerName = state.ledgerName,
            deviceName = state.deviceName,
            role = state.role,
            lastUploadAt = state.lastUploadAt,
            lastSyncAt = state.lastConfirmedSyncAt,
        )
        SettingsEntryRow(
            title = connectionTitle,
            subtitle = connectionSubtitle,
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
            title = "商家别名",
            subtitle = "把不同写法归到同一商家",
            icon = Icons.Filled.Tune,
            onClick = onOpenMerchantAliases,
        )
        SettingsEntryRow(
            title = "数据与导出",
            subtitle = "本地缓存、表格导出说明",
            icon = Icons.Filled.FileDownload,
            onClick = onOpenDataExport,
        )
        SettingsEntryRow(
            title = "通知与提醒",
            subtitle = "待确认、大额和固定支出提醒开关",
            icon = Icons.Filled.Notifications,
            onClick = onOpenNotifications,
        )
        SettingsEntryRow(
            title = "安全与隐私",
            subtitle = if (BuildConfig.REQUIRE_LOCAL_UNLOCK) {
                "本机解锁、本地数据、退出账本"
            } else {
                "本机验证已关闭、本地数据、退出账本"
            },
            icon = Icons.Filled.Security,
            onClick = onOpenSecurity,
        )
        SettingsEntryRow(
            title = "账本 (实验)",
            subtitle = "查看、切换、新建账本",
            icon = Icons.Filled.FolderShared,
            onClick = onOpenLedgers,
        )
        SettingsEntryRow(
            title = "家庭成员",
            subtitle = "查看当前账本成员、角色和状态",
            icon = Icons.Filled.Group,
            onClick = onOpenFamilyMembers,
        )
        SettingsEntryRow(
            title = "加入家庭账本",
            subtitle = "使用本机管理后台生成的邀请明文",
            icon = Icons.Filled.GroupAdd,
            onClick = onOpenJoinFamilyLedger,
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
