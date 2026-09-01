package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals

class AppThemeModeTest {
    @Test
    fun parsesKnownStorageKeysExactly() {
        assertEquals(AppThemeMode.Paper, AppThemeMode.fromStorageKey("paper"))
        assertEquals(AppThemeMode.Midnight, AppThemeMode.fromStorageKey("midnight"))
        assertEquals(AppThemeMode.System, AppThemeMode.fromStorageKey("system"))
    }

    @Test
    fun fallsBackToDefaultForMissingOrRetiredKeys() {
        // 无生产用户/历史数据：一切未知 key（含已退役的 mono/berry/night 等）
        // 一律回落 Default，不保留任何 legacy 映射。
        assertEquals(AppThemeMode.Default, AppThemeMode.fromStorageKey(null))
        assertEquals(AppThemeMode.Default, AppThemeMode.fromStorageKey("mono"))
        assertEquals(AppThemeMode.Default, AppThemeMode.fromStorageKey("berry"))
        assertEquals(AppThemeMode.Default, AppThemeMode.fromStorageKey("night"))
        assertEquals(AppThemeMode.Default, AppThemeMode.fromStorageKey("unknown"))
    }

    @Test
    fun defaultModeIsPaper() {
        assertEquals(AppThemeMode.Paper, AppThemeMode.Default)
    }

    @Test
    fun resolveSkinMapsModesToRenderSkins() {
        assertEquals(AppSkin.Paper, AppThemeMode.Paper.resolveSkin(systemDark = false))
        assertEquals(AppSkin.Paper, AppThemeMode.Paper.resolveSkin(systemDark = true))
        assertEquals(AppSkin.Midnight, AppThemeMode.Midnight.resolveSkin(systemDark = false))
        assertEquals(AppSkin.Midnight, AppThemeMode.Midnight.resolveSkin(systemDark = true))
        assertEquals(AppSkin.Paper, AppThemeMode.System.resolveSkin(systemDark = false))
        assertEquals(AppSkin.Midnight, AppThemeMode.System.resolveSkin(systemDark = true))
    }
}
