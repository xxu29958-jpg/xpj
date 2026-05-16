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

        assertTrue(categories.getValue(BuiltInBackgroundCategory.Minimal).map { it.name }.containsAll(listOf("纸本", "墨白")))
        assertTrue(categories.getValue(BuiltInBackgroundCategory.Nature).map { it.name }.containsAll(listOf("茶雾", "玄夜")))
        assertTrue(categories.getValue(BuiltInBackgroundCategory.Emotion).map { it.name }.contains("暖金"))
        assertTrue(categories.getValue(BuiltInBackgroundCategory.Illustration).map { it.name }.contains("灰雾"))
    }

    @Test
    fun builtInLookupMapsLegacyIdsToNewBackgrounds() {
        assertEquals("paper", BackgroundCatalog.find("harbor")?.id)
        assertEquals("midnight", BackgroundCatalog.find("night")?.id)
        assertNotNull(BackgroundCatalog.find("paper"))
        assertEquals(null, BackgroundCatalog.find("missing"))
    }
}
