package com.ticketbox.data.local

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.BackgroundTransform
import com.ticketbox.domain.model.ImmersionMode
import java.io.File
import kotlin.io.path.createTempDirectory
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest

class BackgroundSettingsDataStoreTest {
    @Test
    fun imageAndCompositionAreReadBackTogether() = runTest {
        val store = newBackgroundStore()
        val settings = BackgroundSettings().withCustomImage("/private/backgrounds/photo.image")
            .copy(transform = BackgroundTransform(scale = 2f, offsetX = -0.5f, offsetY = 0.75f))

        store.saveBackgroundSettings(settings)

        assertEquals(settings, store.settingsFlow.first())
    }

    @Test
    fun emptyStoreReadsDefaultSettings() = runTest {
        val store = newBackgroundStore()

        assertEquals(BackgroundSettings(), store.settingsFlow.first())
    }

    @Test
    fun saveAndReadImmersionMode() = runTest {
        val store = newBackgroundStore()

        store.setImmersionMode(ImmersionMode.Atmosphere)

        assertEquals(ImmersionMode.Atmosphere, store.settingsFlow.first().immersionMode)
    }

    @Test
    fun saveAndReadBackgroundSourceAndBuiltInId() = runTest {
        val store = newBackgroundStore()

        store.saveBackgroundSettings(BackgroundSettings().withBuiltInBackground("harbor"))

        val settings = store.settingsFlow.first()
        assertEquals(BackgroundSource.BuiltIn, settings.source)
        assertEquals("harbor", settings.builtInBackgroundId)
        assertEquals(null, settings.customImagePath)
    }

    @Test
    fun clearBackgroundReturnsToThemeDefault() = runTest {
        val store = newBackgroundStore()
        val original = BackgroundSettings().withCustomImage("/private/backgrounds/photo.image")
            .copy(immersionMode = ImmersionMode.Focus, reduceMotion = true, enableParallax = false)
        store.saveBackgroundSettings(original)

        store.saveBackgroundSettings(original.withoutBackground())

        val settings = store.settingsFlow.first()
        assertEquals(BackgroundSource.ThemeDefault, settings.source)
        assertEquals(null, settings.builtInBackgroundId)
        assertEquals(null, settings.customImagePath)
        assertEquals(ImmersionMode.Focus, settings.immersionMode)
        assertTrue(settings.reduceMotion)
    }

    @Test
    fun customImagePathIsTrimmed() = runTest {
        val store = newBackgroundStore()

        store.saveBackgroundSettings(BackgroundSettings().withCustomImage("  C:\\app\\backgrounds\\custom_background.jpg  "))

        val settings = store.settingsFlow.first()
        assertEquals(BackgroundSource.CustomImage, settings.source)
        assertEquals("C:\\app\\backgrounds\\custom_background.jpg", settings.customImagePath)
    }

    @Test
    fun reduceMotionDisablesParallax() = runTest {
        val store = newBackgroundStore()

        store.setReduceMotion(true)

        val settings = store.settingsFlow.first()
        assertTrue(settings.reduceMotion)
        assertFalse(settings.enableParallax)
    }

    private fun CoroutineScope.newBackgroundStore(): BackgroundSettingsDataStore {
        val dir = createTempDirectory(prefix = "ticketbox-background-store").toFile()
        val file = File(dir, "background.preferences_pb")
        val dataStore = PreferenceDataStoreFactory.create(
            scope = this,
            produceFile = { file },
        )
        return BackgroundSettingsDataStore(dataStore)
    }
}
