package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals

class AppSkinTest {
    @Test
    fun parsesKnownStorageKey() {
        assertEquals(AppSkin.Pomelo, AppSkin.fromStorageKey("pomelo"))
    }

    @Test
    fun fallsBackToDefaultForMissingOrUnknownStorageKey() {
        assertEquals(AppSkin.Default, AppSkin.fromStorageKey(null))
        assertEquals(AppSkin.Default, AppSkin.fromStorageKey("unknown"))
    }
}
