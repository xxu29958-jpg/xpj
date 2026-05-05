package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class BackgroundSettingsTest {
    @Test
    fun defaultSettingsFollowThemeWithBalancedImmersion() {
        val settings = BackgroundSettings()

        assertEquals(BackgroundSource.ThemeDefault, settings.source)
        assertEquals(null, settings.builtInBackgroundId)
        assertEquals(null, settings.customImagePath)
        assertEquals(ImmersionMode.Balanced, settings.immersionMode)
        assertTrue(settings.enableParallax)
        assertFalse(settings.reduceMotion)
    }

    @Test
    fun storageKeysFallbackToStableDefaults() {
        assertEquals(BackgroundSource.BuiltIn, BackgroundSource.fromStorageKey("built_in"))
        assertEquals(BackgroundSource.CustomImage, BackgroundSource.fromStorageKey("custom_image"))
        assertEquals(BackgroundSource.ThemeDefault, BackgroundSource.fromStorageKey("missing"))
        assertEquals(ImmersionMode.Atmosphere, ImmersionMode.fromStorageKey("atmosphere"))
        assertEquals(ImmersionMode.Balanced, ImmersionMode.fromStorageKey("missing"))
    }

    @Test
    fun builtInBackgroundClearsCustomImage() {
        val settings = BackgroundSettings()
            .withCustomImage("C:\\app\\backgrounds\\custom_background.jpg")
            .withBuiltInBackground("harbor")

        assertEquals(BackgroundSource.BuiltIn, settings.source)
        assertEquals("harbor", settings.builtInBackgroundId)
        assertEquals(null, settings.customImagePath)
    }

    @Test
    fun clearBackgroundReturnsToThemeDefault() {
        val settings = BackgroundSettings().withCustomImage("C:\\app\\backgrounds\\custom_background.jpg")

        val cleared = settings.withoutCustomImage()

        assertEquals(BackgroundSource.ThemeDefault, cleared.source)
        assertEquals(null, cleared.builtInBackgroundId)
        assertEquals(null, cleared.customImagePath)
    }

    @Test
    fun missingCustomImageFallsBackToThemeBackground() {
        val settings = BackgroundSettings().withCustomImage("C:\\missing\\image.jpg")

        assertFalse(shouldUseCustomBackground(settings) { false })
        assertTrue(shouldUseCustomBackground(settings) { true })
        assertFalse(shouldUseCustomBackground(settings.copy(customImagePath = null)) { true })
    }
}
