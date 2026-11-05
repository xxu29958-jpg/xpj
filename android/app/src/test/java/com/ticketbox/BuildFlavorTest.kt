package com.ticketbox

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class BuildFlavorTest {
    @Test
    fun advancedToolsFollowAudienceFlavor() {
        assertEquals(BuildConfig.FLAVOR == "internal", BuildConfig.SHOW_ADVANCED_TOOLS)
    }

    @Test
    fun pairingStartsWithAnEditableBlankOrAConfiguredServer() {
        val url = BuildConfig.DEFAULT_SERVER_URL
        assertNotEquals("https://api.example.com", url)
        assertTrue(
            url.isEmpty() || url.startsWith("https://") || url.startsWith("http://"),
        )
        assertEquals(url.trim().trimEnd('/'), url)
    }
}
