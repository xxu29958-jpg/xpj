package com.ticketbox

import kotlin.test.Test
import kotlin.test.assertEquals

class BuildFlavorTest {
    @Test
    fun advancedToolsFollowAudienceFlavor() {
        assertEquals(BuildConfig.FLAVOR == "internal", BuildConfig.SHOW_ADVANCED_TOOLS)
    }

    @Test
    fun debugFlavorsUseOwnerServerAsDefault() {
        assertEquals("https://api.zen70.cn", BuildConfig.DEFAULT_SERVER_URL)
    }
}
