package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.FolderShared
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.Tune
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.BuildConfig
import com.ticketbox.R
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.SettingsUiState

data class SettingsRootNavigationActions(
    val ledgerFamily: SettingsRootLedgerFamilyNavigationActions,
    val dataPrivacy: SettingsRootDataPrivacyNavigationActions,
    val alertsAppearance: SettingsRootAlertsAppearanceNavigationActions,
    val connectionSystem: SettingsRootConnectionSystemNavigationActions,
)

data class SettingsRootLedgerFamilyNavigationActions(
    val onOpenLedgers: () -> Unit,
    val onOpenFamilyMembers: () -> Unit,
    val onOpenMyDevices: () -> Unit,
    val onOpenJoinFamilyLedger: () -> Unit,
)

data class SettingsRootDataPrivacyNavigationActions(
    val onOpenDataExport: () -> Unit,
)

data class SettingsRootAlertsAppearanceNavigationActions(
    val onOpenNotifications: () -> Unit,
    val onOpenAppearance: () -> Unit,
)

data class SettingsRootConnectionSystemNavigationActions(
    val onOpenServer: () -> Unit,
    val onOpenSyncStatus: () -> Unit,
    val onOpenBackgroundTasks: () -> Unit,
    val onOpenSecurity: () -> Unit,
    val onOpenAbout: () -> Unit,
)

@Composable
fun SettingsRootScreen(
    state: SettingsUiState,
    showAdvancedTools: Boolean,
    onBack: (() -> Unit)? = null,
    navigationActions: SettingsRootNavigationActions,
) {
    SettingsPageFrame(
        title = stringResource(R.string.settings_root_page_title),
        subtitle = stringResource(R.string.settings_root_page_subtitle),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap)) {
            val authorityTone = settingsAuthorityTone(state)
            if (authorityTone != DataAuthorityTone.Backend) {
                AppDataAuthorityStrip(
                    tone = authorityTone,
                    localCacheBodyRes = R.string.components_data_authority_settings_cache_body,
                )
            }
            SettingsRootAccountSummary(
                state = state,
                onOpenConnection = navigationActions.connectionSystem.onOpenServer,
            )
            SettingsLedgerFamilySection(state = state, actions = navigationActions.ledgerFamily)
            SettingsDataPrivacySection(actions = navigationActions.dataPrivacy)
            SettingsAlertsAppearanceSection(actions = navigationActions.alertsAppearance)
            SettingsConnectionSystemSection(
                showAdvancedTools = showAdvancedTools,
                actions = navigationActions.connectionSystem,
            )
        }
    }
}

@Composable
private fun SettingsLedgerFamilySection(
    state: SettingsUiState,
    actions: SettingsRootLedgerFamilyNavigationActions,
) {
    SettingsSection(title = stringResource(R.string.settings_root_section_ledger_family), icon = Icons.Filled.Group) {
        SettingsRootEntryGroup {
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_ledgers_title),
                subtitle = stringResource(R.string.settings_root_entry_ledgers_subtitle),
                icon = Icons.Filled.FolderShared,
                onClick = actions.onOpenLedgers,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_family_members_title),
                subtitle = stringResource(R.string.settings_root_entry_family_members_subtitle),
                icon = Icons.Filled.Group,
                onClick = actions.onOpenFamilyMembers,
            )
            if (state.role == LEDGER_ROLE_OWNER) {
                SettingsEntryRow(
                    title = stringResource(R.string.settings_root_entry_my_devices_title),
                    subtitle = stringResource(R.string.settings_root_entry_my_devices_subtitle),
                    icon = Icons.Filled.Devices,
                    onClick = actions.onOpenMyDevices,
                )
            }
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_join_family_title),
                subtitle = stringResource(R.string.settings_root_entry_join_family_subtitle),
                icon = Icons.Filled.GroupAdd,
                onClick = actions.onOpenJoinFamilyLedger,
            )
        }
    }
}

@Composable
private fun SettingsDataPrivacySection(
    actions: SettingsRootDataPrivacyNavigationActions,
) {
    SettingsSection(
        title = stringResource(R.string.settings_root_section_data_privacy),
        icon = Icons.Filled.Security,
    ) {
        SettingsRootEntryGroup {
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_data_export_title),
                subtitle = stringResource(R.string.settings_root_entry_data_export_subtitle),
                icon = Icons.Filled.FileDownload,
                onClick = actions.onOpenDataExport,
            )
        }
    }
}

@Composable
private fun SettingsAlertsAppearanceSection(
    actions: SettingsRootAlertsAppearanceNavigationActions,
) {
    SettingsSection(
        title = stringResource(R.string.settings_root_section_alerts_appearance),
        icon = Icons.Filled.Palette,
    ) {
        SettingsRootEntryGroup {
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_notifications_title),
                subtitle = stringResource(R.string.settings_root_entry_notifications_subtitle),
                icon = Icons.Filled.Notifications,
                onClick = actions.onOpenNotifications,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_appearance_title),
                subtitle = stringResource(R.string.settings_root_entry_appearance_subtitle),
                icon = Icons.Filled.Palette,
                onClick = actions.onOpenAppearance,
            )
        }
    }
}

@Composable
private fun SettingsConnectionSystemSection(
    showAdvancedTools: Boolean,
    actions: SettingsRootConnectionSystemNavigationActions,
) {
    val connectionTitle = stringResource(
        if (showAdvancedTools) {
            R.string.settings_root_connection_title_advanced
        } else {
            R.string.settings_root_connection_title_basic
        },
    )
    val connectionSubtitle = stringResource(
        if (showAdvancedTools) {
            R.string.settings_root_connection_subtitle_advanced
        } else {
            R.string.settings_root_connection_subtitle_basic
        },
    )
    SettingsSection(
        title = stringResource(R.string.settings_root_section_connection_system),
        icon = Icons.Filled.Security,
    ) {
        SettingsRootEntryGroup {
            SettingsEntryRow(
                title = connectionTitle,
                subtitle = connectionSubtitle,
                icon = Icons.Filled.CloudDone,
                onClick = actions.onOpenServer,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_offline_sync_title),
                subtitle = stringResource(R.string.settings_root_entry_offline_sync_subtitle),
                icon = Icons.Filled.Sync,
                onClick = actions.onOpenSyncStatus,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_background_tasks_title),
                subtitle = stringResource(R.string.settings_root_entry_background_tasks_subtitle),
                icon = Icons.Filled.Tune,
                onClick = actions.onOpenBackgroundTasks,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_security_title),
                subtitle = stringResource(
                    if (BuildConfig.REQUIRE_LOCAL_UNLOCK) {
                        R.string.settings_root_entry_security_subtitle_locked
                    } else {
                        R.string.settings_root_entry_security_subtitle_unlocked
                    },
                ),
                icon = Icons.Filled.Security,
                onClick = actions.onOpenSecurity,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_about_title),
                subtitle = stringResource(R.string.settings_root_entry_about_subtitle),
                icon = Icons.Filled.Info,
                onClick = actions.onOpenAbout,
            )
        }
    }
}

@Composable
private fun SettingsRootEntryGroup(
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(content = content)
}

private fun settingsAuthorityTone(state: SettingsUiState): DataAuthorityTone = when {
    state.busy -> DataAuthorityTone.Refreshing
    state.serverSettingsFresh -> DataAuthorityTone.Backend
    state.serverSettings == null && state.message == null -> DataAuthorityTone.Refreshing
    else -> DataAuthorityTone.LocalCache
}
