package com.ticketbox

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class BuildFlavorTest {
    @Test
    fun advancedToolsFollowAudienceFlavor() {
        assertEquals(BuildConfig.FLAVOR == "internal", BuildConfig.SHOW_ADVANCED_TOOLS)
    }

    @Test
    fun debugFlavorsExposeConfiguredServerDefault() {
        assertTrue(
            BuildConfig.DEFAULT_SERVER_URL.startsWith("https://") ||
                BuildConfig.DEFAULT_SERVER_URL.startsWith("http://"),
        )
        assertEquals(
            BuildConfig.DEFAULT_SERVER_URL.trim().trimEnd('/'),
            BuildConfig.DEFAULT_SERVER_URL,
        )
    }
}
