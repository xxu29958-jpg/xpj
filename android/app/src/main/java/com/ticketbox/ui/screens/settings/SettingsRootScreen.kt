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
import androidx.compose.material.icons.automirrored.filled.Label
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.DashboardCustomize
import androidx.compose.material.icons.filled.Devices
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
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import com.ticketbox.BuildConfig
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
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
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.ScreenHeader
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.AppSpacing
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
    onOpenDashboardCards: () -> Unit,
    onOpenCategoryRules: () -> Unit,
    onOpenMerchantAliases: () -> Unit,
    onOpenTagManagement: () -> Unit,
    onOpenDataExport: () -> Unit,
    onOpenNotifications: () -> Unit,
    onOpenSecurity: () -> Unit,
    onOpenLedgers: () -> Unit = {},
    onOpenFamilyMembers: () -> Unit = {},
    onOpenMyDevices: () -> Unit = {},
    onOpenJoinFamilyLedger: () -> Unit = {},
    onOpenBillSplits: () -> Unit = {},
    onOpenBackgroundTasks: () -> Unit = {},
    onOpenSyncStatus: () -> Unit = {},
    onOpenIncomePlans: () -> Unit = {},
    onOpenAbout: () -> Unit,
) {
    val connectionTitle = if (showAdvancedTools) {
        stringResource(R.string.settings_root_connection_title_advanced)
    } else {
        stringResource(R.string.settings_root_connection_title_basic)
    }
    val connectionSubtitle = if (showAdvancedTools) {
        stringResource(R.string.settings_root_connection_subtitle_advanced)
    } else {
        stringResource(R.string.settings_root_connection_subtitle_basic)
    }
    SettingsPageFrame(
        title = stringResource(R.string.settings_root_page_title),
        subtitle = stringResource(R.string.settings_root_page_subtitle),
        onBack = null,
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap)) {
            AccountStatusCard(
                serverSettings = state.serverSettings,
                accountName = state.accountName,
                ledgerName = state.ledgerName,
                deviceName = state.deviceName,
                role = state.role,
                lastUploadAt = state.lastUploadAt,
                lastSyncAt = state.lastConfirmedSyncAt,
            )
            // 轴2 IA(owner 拍板 A1):17 入口由旧 5 组(账本与同步/记账设置/家庭协作/
            // 外观与数据/安全与关于)重排为贴三域的 4 组,排序=家庭日常 → 记账配置 →
            // 个性化 → 系统,频率递减。入口不增不减,纯重排+组重命名。
            SettingsSection(title = stringResource(R.string.settings_root_section_ledger_family), icon = Icons.Filled.Group) {
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_ledgers_title),
                    subtitle = stringResource(R.string.settings_root_entry_ledgers_subtitle),
                    icon = Icons.Filled.FolderShared,
                    onClick = onOpenLedgers,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_family_members_title),
                    subtitle = stringResource(R.string.settings_root_entry_family_members_subtitle),
                    icon = Icons.Filled.Group,
                    onClick = onOpenFamilyMembers,
                )
                // My devices is an owner-only management surface (backend slice 6a
                // gates the list on manager context → 403/404), so the entry is
                // shown to owners only; non-owners never see a dead-ending row.
                if (state.role == LEDGER_ROLE_OWNER) {
                    SettingsEntryRow(
                        title = stringResource(R.string.settings_root_entry_my_devices_title),
                        subtitle = stringResource(R.string.settings_root_entry_my_devices_subtitle),
                        icon = Icons.Filled.Devices,
                        onClick = onOpenMyDevices,
                    )
                }
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_join_family_title),
                    subtitle = stringResource(R.string.settings_root_entry_join_family_subtitle),
                    icon = Icons.Filled.GroupAdd,
                    onClick = onOpenJoinFamilyLedger,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_bill_splits_title),
                    subtitle = stringResource(R.string.settings_root_entry_bill_splits_subtitle),
                    icon = Icons.Filled.Group,
                    onClick = onOpenBillSplits,
                )
            }
            SettingsSection(title = stringResource(R.string.settings_root_section_bookkeeping_data), icon = Icons.Filled.Category) {
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_category_rules_title),
                    subtitle = stringResource(R.string.settings_root_entry_category_rules_subtitle),
                    icon = Icons.Filled.Category,
                    onClick = onOpenCategoryRules,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_merchant_aliases_title),
                    subtitle = stringResource(R.string.settings_root_entry_merchant_aliases_subtitle),
                    icon = Icons.Filled.Tune,
                    onClick = onOpenMerchantAliases,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_tag_management_title),
                    subtitle = stringResource(R.string.settings_root_entry_tag_management_subtitle),
                    icon = Icons.AutoMirrored.Filled.Label,
                    onClick = onOpenTagManagement,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_dashboard_cards_title),
                    subtitle = stringResource(R.string.settings_root_entry_dashboard_cards_subtitle),
                    icon = Icons.Filled.DashboardCustomize,
                    onClick = onOpenDashboardCards,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_data_export_title),
                    subtitle = stringResource(R.string.settings_root_entry_data_export_subtitle),
                    icon = Icons.Filled.FileDownload,
                    onClick = onOpenDataExport,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_income_plans_title),
                    subtitle = stringResource(R.string.settings_root_entry_income_plans_subtitle),
                    icon = Icons.Filled.AccountBalanceWallet,
                    onClick = onOpenIncomePlans,
                )
            }
            SettingsSection(title = stringResource(R.string.settings_root_section_alerts_appearance), icon = Icons.Filled.Palette) {
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_notifications_title),
                    subtitle = stringResource(R.string.settings_root_entry_notifications_subtitle),
                    icon = Icons.Filled.Notifications,
                    onClick = onOpenNotifications,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_appearance_title),
                    subtitle = stringResource(R.string.settings_root_entry_appearance_subtitle),
                    icon = Icons.Filled.Palette,
                    onClick = onOpenAppearance,
                )
            }
            SettingsSection(title = stringResource(R.string.settings_root_section_connection_system), icon = Icons.Filled.Security) {
                SettingsEntryRow(
                    title = connectionTitle,
                    subtitle = connectionSubtitle,
                    icon = Icons.Filled.CloudDone,
                    onClick = onOpenServer,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_offline_sync_title),
                    subtitle = stringResource(R.string.settings_root_entry_offline_sync_subtitle),
                    icon = Icons.Filled.Sync,
                    onClick = onOpenSyncStatus,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_background_tasks_title),
                    subtitle = stringResource(R.string.settings_root_entry_background_tasks_subtitle),
                    icon = Icons.Filled.Tune,
                    onClick = onOpenBackgroundTasks,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_security_title),
                    subtitle = if (BuildConfig.REQUIRE_LOCAL_UNLOCK) {
                        stringResource(R.string.settings_root_entry_security_subtitle_locked)
                    } else {
                        stringResource(R.string.settings_root_entry_security_subtitle_unlocked)
                    },
                    icon = Icons.Filled.Security,
                    onClick = onOpenSecurity,
                )
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_about_title),
                    subtitle = stringResource(R.string.settings_root_entry_about_subtitle),
                    icon = Icons.Filled.Info,
                    onClick = onOpenAbout,
                )
            }
        }
    }
}
