package com.ticketbox.domain.model

/**
 * 本机偏好主题模式。渲染主题（[AppSkin]）只剩 Paper/Midnight 两套；System 由平台
 * dark mode 在 [resolveSkin] 解析到具体 skin。无生产用户/历史数据：[fromStorageKey]
 * 只接受精确 key，其余一切（含已退役的 mono/berry/night 等）一律回落 [Default]，
 * 不保留任何 legacy 映射。
 */
enum class AppThemeMode(
    val storageKey: String,
    val displayName: String,
) {
    Paper(
        storageKey = "paper",
        displayName = "晨纸",
    ),
    Midnight(
        storageKey = "midnight",
        displayName = "玄夜",
    ),
    System(
        storageKey = "system",
        displayName = "跟随系统",
    );

    fun resolveSkin(systemDark: Boolean): AppSkin = when (this) {
        Paper -> AppSkin.Paper
        Midnight -> AppSkin.Midnight
        System -> if (systemDark) AppSkin.Midnight else AppSkin.Paper
    }

    companion object {
        val Default: AppThemeMode = Paper

        fun fromStorageKey(value: String?): AppThemeMode {
            return entries.firstOrNull { mode -> mode.storageKey == value } ?: Default
        }
    }
}
