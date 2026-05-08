package com.ticketbox

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class BuildFlavorTest {
    @Test
    fun grayDebugDoesNotExposeAdvancedTools() {
        assertFalse(BuildConfig.SHOW_ADVANCED_TOOLS)
    }

    @Test
    fun grayDebugUsesOwnerServerAsDefault() {
        assertEquals("https://api.zen70.cn", BuildConfig.DEFAULT_SERVER_URL)
    }
}
