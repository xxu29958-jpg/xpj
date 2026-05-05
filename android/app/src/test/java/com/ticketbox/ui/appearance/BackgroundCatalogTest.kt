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
    fun catalogContainsRequiredCategories() {
        val categories = BackgroundCatalog.entries.groupBy { it.category }

        assertTrue(categories.getValue(BuiltInBackgroundCategory.Nature).map { it.name }.containsAll(listOf("松雾", "港湾", "夜幕")))
        assertTrue(categories.getValue(BuiltInBackgroundCategory.Emotion).map { it.name }.containsAll(listOf("柚光", "莓果")))
        assertTrue(categories.getValue(BuiltInBackgroundCategory.Minimal).map { it.name }.containsAll(listOf("纸感", "暖雾")))
        assertTrue(categories.getValue(BuiltInBackgroundCategory.Illustration).map { it.name }.contains("云层"))
    }

    @Test
    fun builtInLookupFindsHarbor() {
        assertNotNull(BackgroundCatalog.find("harbor"))
        assertEquals(null, BackgroundCatalog.find("missing"))
    }
}
