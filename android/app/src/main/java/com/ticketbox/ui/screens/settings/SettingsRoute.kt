package com.ticketbox.ui.screens.settings

enum class SettingsRoute {
    Root,
    Server,
    Appearance,
    BackgroundGallery,
    // 全局背景批:编辑目标不再走路由参数,draft 由 AppearanceViewModel 唯一持有
    // (editor: BackgroundEditorState?);路由只表达「编辑器打开」这一导航事实。
    BackgroundEditor,
    DataExport,
    NotificationPreferences,
    SecurityPrivacy,
    Ledgers,
    FamilyMembers,
    MyDevices,
    JoinFamilyLedger,
    BackgroundTasks,
    SyncStatus,
    About,
}
