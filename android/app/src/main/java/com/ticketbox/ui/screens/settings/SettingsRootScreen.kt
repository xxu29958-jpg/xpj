package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.ticketbox.BuildConfig
import com.ticketbox.R
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.asTextStyle
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.SettingsUiState

data class SettingsRootNavigationActions(
    val ledgerFamily: SettingsRootLedgerFamilyNavigationActions,
    val dataPrivacy: SettingsRootDataPrivacyNavigationActions,
    val alertsAppearance: SettingsRootAlertsAppearanceNavigationActions,
    val connectionSystem: SettingsRootConnectionSystemNavigationActions,
)

data class SettingsRootLedgerFamilyNavigationActions(
    val onOpenAccountProfile: () -> Unit,
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
            SettingsLedgerFamilySection(navigationActions.ledgerFamily)
            SettingsDailySection(navigationActions)
            SettingsConnectionSystemSection(showAdvancedTools, navigationActions.connectionSystem)
            SettingsDetailRow(
                title = stringResource(R.string.settings_account_current_ledger_label),
                subtitle = state.ledgerName.orEmpty(),
                icon = R.drawable.ic_lucide_cloud_check,
            ) {
                SettingsRootAccountSummary(state, navigationActions.connectionSystem.onOpenServer)
            }
        }
    }
}

@Composable
private fun SettingsLedgerFamilySection(actions: SettingsRootLedgerFamilyNavigationActions) {
    SettingsRootSection(stringResource(R.string.settings_root_section_ledger_family)) {
        SettingsDetailRow(
            title = stringResource(R.string.settings_root_family_directory_title),
            subtitle = "",
            icon = R.drawable.ic_lucide_users,
        ) {
            SettingsEntryRow(
                title = stringResource(R.string.account_profile_title),
                subtitle = stringResource(R.string.account_profile_subtitle),
                icon = R.drawable.ic_lucide_user_round,
                onClick = actions.onOpenAccountProfile,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_ledgers_title),
                subtitle = stringResource(R.string.settings_root_entry_ledgers_subtitle),
                icon = R.drawable.ic_lucide_book_open,
                onClick = actions.onOpenLedgers,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_family_members_title),
                subtitle = stringResource(R.string.settings_root_entry_family_members_subtitle),
                icon = R.drawable.ic_lucide_users,
                onClick = actions.onOpenFamilyMembers,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_join_family_title),
                subtitle = stringResource(R.string.settings_root_entry_join_family_subtitle),
                icon = R.drawable.ic_lucide_user_round_plus,
                onClick = actions.onOpenJoinFamilyLedger,
            )
        }
        SettingsEntryRow(
            title = stringResource(R.string.settings_root_entry_my_devices_title),
            subtitle = "",
            icon = R.drawable.ic_lucide_monitor_smartphone,
            onClick = actions.onOpenMyDevices,
        )
    }
}

@Composable
private fun SettingsDailySection(actions: SettingsRootNavigationActions) {
    SettingsRootSection(stringResource(R.string.settings_root_section_daily)) {
        SettingsDetailRow(
            title = stringResource(R.string.settings_root_alerts_directory_title),
            subtitle = "",
            icon = R.drawable.ic_lucide_palette,
        ) {
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_notifications_title),
                subtitle = stringResource(R.string.settings_root_entry_notifications_subtitle),
                icon = R.drawable.ic_lucide_bell,
                onClick = actions.alertsAppearance.onOpenNotifications,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_appearance_title),
                subtitle = stringResource(R.string.settings_root_entry_appearance_subtitle),
                icon = R.drawable.ic_lucide_palette,
                onClick = actions.alertsAppearance.onOpenAppearance,
            )
        }
        SettingsDetailRow(
            title = stringResource(R.string.settings_root_section_data_privacy),
            subtitle = "",
            icon = R.drawable.ic_lucide_shield_check,
        ) {
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_data_export_title),
                subtitle = stringResource(R.string.settings_root_entry_data_export_subtitle),
                icon = R.drawable.ic_lucide_download,
                onClick = actions.dataPrivacy.onOpenDataExport,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_security_title),
                subtitle = stringResource(
                    if (BuildConfig.REQUIRE_LOCAL_UNLOCK) R.string.settings_root_entry_security_subtitle_locked
                    else R.string.settings_root_entry_security_subtitle_unlocked,
                ),
                icon = R.drawable.ic_lucide_shield_check,
                onClick = actions.connectionSystem.onOpenSecurity,
            )
        }
    }
}

@Composable
private fun SettingsConnectionSystemSection(
    showAdvancedTools: Boolean,
    actions: SettingsRootConnectionSystemNavigationActions,
) {
    SettingsRootSection(stringResource(R.string.settings_root_section_connection_system)) {
        SettingsDetailRow(
            title = stringResource(R.string.settings_root_sync_directory_title),
            subtitle = "",
            icon = R.drawable.ic_lucide_refresh_cw,
        ) {
            SettingsEntryRow(
                title = stringResource(
                    if (showAdvancedTools) R.string.settings_root_connection_title_advanced
                    else R.string.settings_root_connection_title_basic,
                ),
                subtitle = stringResource(
                    if (showAdvancedTools) R.string.settings_root_connection_subtitle_advanced
                    else R.string.settings_root_connection_subtitle_basic,
                ),
                icon = R.drawable.ic_lucide_cloud_check,
                onClick = actions.onOpenServer,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_offline_sync_title),
                subtitle = stringResource(R.string.settings_root_entry_offline_sync_subtitle),
                icon = R.drawable.ic_lucide_refresh_cw,
                onClick = actions.onOpenSyncStatus,
            )
            SettingsEntryRow(
                title = stringResource(R.string.settings_root_entry_background_tasks_title),
                subtitle = stringResource(R.string.settings_root_entry_background_tasks_subtitle),
                icon = R.drawable.ic_lucide_sliders_horizontal,
                onClick = actions.onOpenBackgroundTasks,
            )
        }
        SettingsEntryRow(
            title = stringResource(R.string.settings_root_entry_about_title),
            subtitle = "",
            icon = R.drawable.ic_lucide_info,
            onClick = actions.onOpenAbout,
        )
    }
}

@Composable
private fun SettingsRootSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(
            title,
            style = AppTextHierarchy.heading.asTextStyle(),
            fontWeight = AppTextHierarchy.heading.weight,
            modifier = Modifier.semantics { heading() },
        )
        Column(content = content)
    }
}


private fun settingsAuthorityTone(state: SettingsUiState): DataAuthorityTone = when {
    state.busy -> DataAuthorityTone.Refreshing
    state.serverSettingsFresh -> DataAuthorityTone.Backend
    state.serverSettings == null && state.message == null -> DataAuthorityTone.Refreshing
    else -> DataAuthorityTone.LocalCache
}
