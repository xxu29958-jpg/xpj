package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.BackgroundSettings

sealed class SettingsRoute {
    data object Root : SettingsRoute()
    data object Server : SettingsRoute()
    data object Appearance : SettingsRoute()
    data object BackgroundGallery : SettingsRoute()
    data class BackgroundPreview(
        val settings: BackgroundSettings,
        val title: String,
    ) : SettingsRoute()
    data class BackgroundCrop(
        val sourcePath: String,
    ) : SettingsRoute()
    data object DashboardCards : SettingsRoute()
    data object CategoryRules : SettingsRoute()
    data object MerchantAliases : SettingsRoute()
    data object DataExport : SettingsRoute()
    data object NotificationPreferences : SettingsRoute()
    data object SecurityPrivacy : SettingsRoute()
    data object Ledgers : SettingsRoute()
    data object FamilyMembers : SettingsRoute()
    data object JoinFamilyLedger : SettingsRoute()
    data object About : SettingsRoute()
}
