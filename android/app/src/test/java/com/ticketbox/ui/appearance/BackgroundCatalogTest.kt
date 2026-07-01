package com.ticketbox.ui.appearance

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class BackgroundCatalogTest {
    @Test
    fun catalogIdsAreUnique() {
        val ids = BackgroundCatalog.entries.map { it.id }

        assertEquals(ids.size, ids.toSet().size)
    }

    @Test
    fun catalogContainsNewThemeAlignedBackgrounds() {
        val categories = BackgroundCatalog.entries.groupBy { it.category }

        assertTrue(categories.getValue(BuiltInBackgroundCategory.Minimal).map { it.id }.containsAll(listOf("paper", "mono")))
        assertTrue(categories.getValue(BuiltInBackgroundCategory.Nature).map { it.id }.containsAll(listOf("paper_warm", "midnight")))
        assertTrue(categories.getValue(BuiltInBackgroundCategory.Emotion).map { it.id }.contains("midnight_gold"))
        assertTrue(categories.getValue(BuiltInBackgroundCategory.Illustration).map { it.id }.contains("mono_fog"))
    }

    @Test
    fun builtInLookupMapsLegacyIdsToNewBackgrounds() {
        assertEquals("paper", BackgroundCatalog.find("harbor")?.id)
        assertEquals("midnight", BackgroundCatalog.find("night")?.id)
        assertNotNull(BackgroundCatalog.find("paper"))
        assertEquals(null, BackgroundCatalog.find("missing"))
    }
}
