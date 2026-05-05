package com.ticketbox

import kotlin.test.Test
import kotlin.test.assertFalse

class BuildFlavorTest {
    @Test
    fun grayDebugDoesNotExposeAdvancedTools() {
        assertFalse(BuildConfig.SHOW_ADVANCED_TOOLS)
    }
}
