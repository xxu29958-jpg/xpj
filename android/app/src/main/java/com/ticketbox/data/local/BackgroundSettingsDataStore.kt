package com.ticketbox.data.local

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.BackgroundTransform
import com.ticketbox.domain.model.ImmersionMode
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

class BackgroundSettingsDataStore(
    private val dataStore: DataStore<Preferences>,
) {
    val settingsFlow: Flow<BackgroundSettings> = dataStore.data.map { preferences ->
        BackgroundSettings(
            source = BackgroundSource.fromStorageKey(preferences[BACKGROUND_SOURCE]),
            builtInBackgroundId = preferences[BUILT_IN_BACKGROUND_ID],
            customImagePath = preferences[CUSTOM_BACKGROUND_PATH],
            immersionMode = ImmersionMode.fromStorageKey(preferences[IMMERSION_MODE]),
            enableParallax = preferences[BACKGROUND_PARALLAX] ?: true,
            reduceMotion = preferences[REDUCE_MOTION] ?: false,
            transform = BackgroundTransform(
                scale = preferences[BACKGROUND_SCALE] ?: 1f,
                offsetX = preferences[BACKGROUND_OFFSET_X] ?: 0f,
                offsetY = preferences[BACKGROUND_OFFSET_Y] ?: 0f,
            ),
        )
    }

    suspend fun saveBackgroundSettings(settings: BackgroundSettings) {
        dataStore.edit { preferences ->
            preferences[BACKGROUND_SOURCE] = settings.source.storageKey
            when (settings.source) {
                BackgroundSource.ThemeDefault -> {
                    preferences.remove(BUILT_IN_BACKGROUND_ID)
                    preferences.remove(CUSTOM_BACKGROUND_PATH)
                }
                BackgroundSource.BuiltIn -> {
                    val builtInId = settings.builtInBackgroundId?.trim()
                    require(!builtInId.isNullOrBlank()) { "内置背景不能为空。" }
                    preferences[BUILT_IN_BACKGROUND_ID] = builtInId
                    preferences.remove(CUSTOM_BACKGROUND_PATH)
                }
                BackgroundSource.CustomImage -> {
                    val cleanPath = settings.customImagePath?.trim()
                    require(!cleanPath.isNullOrBlank()) { "背景图片路径不能为空。" }
                    preferences[CUSTOM_BACKGROUND_PATH] = cleanPath
                    preferences.remove(BUILT_IN_BACKGROUND_ID)
                }
            }
            preferences[IMMERSION_MODE] = settings.immersionMode.storageKey
            preferences[BACKGROUND_PARALLAX] = settings.enableParallax && !settings.reduceMotion
            preferences[REDUCE_MOTION] = settings.reduceMotion
            preferences[BACKGROUND_SCALE] = settings.transform.scale
            preferences[BACKGROUND_OFFSET_X] = settings.transform.offsetX
            preferences[BACKGROUND_OFFSET_Y] = settings.transform.offsetY
        }
    }

    suspend fun setImmersionMode(mode: ImmersionMode) {
        dataStore.edit { preferences ->
            preferences[IMMERSION_MODE] = mode.storageKey
        }
    }

    suspend fun setParallaxEnabled(enabled: Boolean) {
        dataStore.edit { preferences ->
            preferences[BACKGROUND_PARALLAX] = enabled
        }
    }

    suspend fun setReduceMotion(enabled: Boolean) {
        dataStore.edit { preferences ->
            preferences[REDUCE_MOTION] = enabled
            if (enabled) {
                preferences[BACKGROUND_PARALLAX] = false
            }
        }
    }

    companion object {
        val BACKGROUND_SOURCE = stringPreferencesKey("background_source")
        val BUILT_IN_BACKGROUND_ID = stringPreferencesKey("built_in_background_id")
        val CUSTOM_BACKGROUND_PATH = stringPreferencesKey("custom_background_path")
        val IMMERSION_MODE = stringPreferencesKey("immersion_mode")
        val BACKGROUND_PARALLAX = booleanPreferencesKey("background_parallax")
        val REDUCE_MOTION = booleanPreferencesKey("reduce_motion")
        val BACKGROUND_SCALE = floatPreferencesKey("background_scale")
        val BACKGROUND_OFFSET_X = floatPreferencesKey("background_offset_x")
        val BACKGROUND_OFFSET_Y = floatPreferencesKey("background_offset_y")
    }
}
