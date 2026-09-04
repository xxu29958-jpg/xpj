package com.ticketbox.ui.screens.settings

sealed class SettingsRoute {
    data object Root : SettingsRoute()
    data object Server : SettingsRoute()
    data object Appearance : SettingsRoute()
    data object BackgroundGallery : SettingsRoute()
    // 全局背景批:编辑目标不再走路由参数,draft 由 AppearanceViewModel 唯一持有
    // (editor: BackgroundEditorState?);路由只表达「编辑器打开」这一导航事实。
    data object BackgroundEditor : SettingsRoute()
    data object DataExport : SettingsRoute()
    data object NotificationPreferences : SettingsRoute()
    data object SecurityPrivacy : SettingsRoute()
    data object Ledgers : SettingsRoute()
    data object FamilyMembers : SettingsRoute()
    data object MyDevices : SettingsRoute()
    data object JoinFamilyLedger : SettingsRoute()
    data object BackgroundTasks : SettingsRoute()
    data object SyncStatus : SettingsRoute()
    data object About : SettingsRoute()
}
