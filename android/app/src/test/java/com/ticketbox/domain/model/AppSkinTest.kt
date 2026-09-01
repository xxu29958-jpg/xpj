package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals

class AppSkinTest {
    @Test
    fun shipsExactlyPaperAndMidnight() {
        assertEquals(listOf(AppSkin.Paper, AppSkin.Midnight), AppSkin.entries.toList())
    }

    @Test
    fun defaultSkinIsPaper() {
        assertEquals(AppSkin.Paper, AppSkin.Default)
    }
}
