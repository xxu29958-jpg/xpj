package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals

class AppSkinTest {
    @Test
    fun parsesKnownStorageKey() {
        assertEquals(AppSkin.Paper, AppSkin.fromStorageKey("paper"))
        assertEquals(AppSkin.Mono, AppSkin.fromStorageKey("mono"))
        assertEquals(AppSkin.Midnight, AppSkin.fromStorageKey("midnight"))
    }

    @Test
    fun fallsBackToDefaultForMissingOrUnknownStorageKey() {
        assertEquals(AppSkin.Default, AppSkin.fromStorageKey(null))
        assertEquals(AppSkin.Default, AppSkin.fromStorageKey("unknown"))
    }

    @Test
    fun mapsLegacySkinKeysToCurrentSkins() {
        // v0.10：5 套旧 skin 退役。旧 SharedPreferences 值应自动映射到新 skin。
        // harbor 是旧默认浅色入口，继续落到 paper，避免默认视觉跳深色。
        assertEquals(AppSkin.Paper, AppSkin.fromStorageKey("pine"))
        assertEquals(AppSkin.Paper, AppSkin.fromStorageKey("pomelo"))
        assertEquals(AppSkin.Paper, AppSkin.fromStorageKey("harbor"))
        assertEquals(AppSkin.Mono, AppSkin.fromStorageKey("berry"))
        assertEquals(AppSkin.Midnight, AppSkin.fromStorageKey("night"))
    }
}
