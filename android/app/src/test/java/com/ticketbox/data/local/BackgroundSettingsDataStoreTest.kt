package com.ticketbox.data.local

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
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

        store.clearBackground()

        val settings = store.settingsFlow.first()
        assertEquals(BackgroundSource.ThemeDefault, settings.source)
        assertEquals(null, settings.builtInBackgroundId)
        assertEquals(null, settings.customImagePath)
    }

    @Test
    fun customImagePathIsTrimmed() = runTest {
        val store = newBackgroundStore()

        store.saveBackgroundImagePath("  C:\\app\\backgrounds\\custom_background.jpg  ")

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

    @Test
    fun cropModePersists() = runTest {
        val store = newBackgroundStore()

        store.setBackgroundCropMode(BackgroundCropMode.Bottom)

        assertEquals(BackgroundCropMode.Bottom, store.settingsFlow.first().cropMode)
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
