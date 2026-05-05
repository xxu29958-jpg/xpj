package com.ticketbox.data.local

import android.content.Context
import androidx.core.content.edit
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.ImmersionMode
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.ticketboxBackgroundDataStore by preferencesDataStore(
    name = "ticketbox_background_settings",
)

class LocalSettingsStore(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("ticketbox_settings", Context.MODE_PRIVATE)

    val backgroundSettingsFlow: Flow<BackgroundSettings> = appContext.ticketboxBackgroundDataStore.data
        .map { preferences ->
            BackgroundSettings(
                source = BackgroundSource.fromStorageKey(preferences[BACKGROUND_SOURCE]),
                customImagePath = preferences[CUSTOM_BACKGROUND_PATH],
                immersionMode = ImmersionMode.fromStorageKey(preferences[IMMERSION_MODE]),
                enableParallax = preferences[BACKGROUND_PARALLAX] ?: true,
                reduceMotion = preferences[REDUCE_MOTION] ?: false,
            )
        }

    fun serverUrl(): String? = prefs.getString(KEY_SERVER_URL, null)

    fun appSkinKey(): String? = prefs.getString(KEY_APP_SKIN, null)

    fun monthlyBudgetCents(): Long? {
        val value = prefs.getLong(KEY_MONTHLY_BUDGET_CENTS, NO_BUDGET)
        return value.takeIf { it > 0L }
    }

    fun saveMonthlyBudgetCents(amountCents: Long?) {
        prefs.edit {
            if (amountCents == null || amountCents <= 0L) {
                remove(KEY_MONTHLY_BUDGET_CENTS)
            } else {
                putLong(KEY_MONTHLY_BUDGET_CENTS, amountCents)
            }
        }
    }

    fun lastConfirmedSyncAt(): String? = prefs.getString(KEY_LAST_CONFIRMED_SYNC_AT, null)

    fun saveLastConfirmedSyncAt(value: String) {
        prefs.edit {
            putString(KEY_LAST_CONFIRMED_SYNC_AT, value)
        }
    }

    fun clearLastConfirmedSyncAt() {
        prefs.edit {
            remove(KEY_LAST_CONFIRMED_SYNC_AT)
        }
    }

    fun lastUploadAt(): String? = prefs.getString(KEY_LAST_UPLOAD_AT, null)

    fun saveLastUploadAt(value: String) {
        prefs.edit {
            putString(KEY_LAST_UPLOAD_AT, value)
        }
    }

    fun saveAppSkinKey(skinKey: String) {
        prefs.edit {
            putString(KEY_APP_SKIN, skinKey)
        }
    }

    fun saveServerUrl(serverUrl: String) {
        prefs.edit {
            putString(KEY_SERVER_URL, serverUrl.trim().trimEnd('/'))
        }
    }

    fun isBound(): Boolean = !serverUrl().isNullOrBlank()

    fun markUnlocked() {
        prefs.edit {
            putLong(KEY_LAST_UNLOCKED_AT, System.currentTimeMillis())
        }
    }

    fun markBackgrounded() {
        prefs.edit {
            putLong(KEY_LAST_BACKGROUNDED_AT, System.currentTimeMillis())
        }
    }

    fun requiresUnlock(): Boolean {
        val lastUnlockedAt = prefs.getLong(KEY_LAST_UNLOCKED_AT, 0L)
        if (lastUnlockedAt == 0L) return true
        val lastBackgroundedAt = prefs.getLong(KEY_LAST_BACKGROUNDED_AT, 0L)
        if (lastBackgroundedAt == 0L || lastBackgroundedAt <= lastUnlockedAt) return false
        return System.currentTimeMillis() - lastBackgroundedAt > LOCK_AFTER_MS
    }

    fun clear() {
        prefs.edit {
            clear()
        }
    }

    suspend fun saveBackgroundImagePath(path: String) {
        val cleanPath = path.trim()
        require(cleanPath.isNotBlank()) { "背景图片路径不能为空。" }
        appContext.ticketboxBackgroundDataStore.edit { preferences ->
            preferences[BACKGROUND_SOURCE] = BackgroundSource.CustomImage.storageKey
            preferences[CUSTOM_BACKGROUND_PATH] = cleanPath
        }
    }

    suspend fun clearBackgroundImage() {
        appContext.ticketboxBackgroundDataStore.edit { preferences ->
            preferences[BACKGROUND_SOURCE] = BackgroundSource.ThemeDefault.storageKey
            preferences.remove(CUSTOM_BACKGROUND_PATH)
        }
    }

    suspend fun setImmersionMode(mode: ImmersionMode) {
        appContext.ticketboxBackgroundDataStore.edit { preferences ->
            preferences[IMMERSION_MODE] = mode.storageKey
        }
    }

    suspend fun setParallaxEnabled(enabled: Boolean) {
        appContext.ticketboxBackgroundDataStore.edit { preferences ->
            preferences[BACKGROUND_PARALLAX] = enabled
        }
    }

    suspend fun setReduceMotion(enabled: Boolean) {
        appContext.ticketboxBackgroundDataStore.edit { preferences ->
            preferences[REDUCE_MOTION] = enabled
            if (enabled) {
                preferences[BACKGROUND_PARALLAX] = false
            }
        }
    }

    private companion object {
        const val KEY_SERVER_URL = "server_url"
        const val KEY_APP_SKIN = "app_skin"
        const val KEY_MONTHLY_BUDGET_CENTS = "monthly_budget_cents"
        const val KEY_LAST_CONFIRMED_SYNC_AT = "last_confirmed_sync_at"
        const val KEY_LAST_UPLOAD_AT = "last_upload_at"
        const val KEY_LAST_UNLOCKED_AT = "last_unlocked_at"
        const val KEY_LAST_BACKGROUNDED_AT = "last_backgrounded_at"
        const val NO_BUDGET = -1L
        const val LOCK_AFTER_MS = 5 * 60 * 1000L
        val BACKGROUND_SOURCE = stringPreferencesKey("background_source")
        val CUSTOM_BACKGROUND_PATH = stringPreferencesKey("custom_background_path")
        val IMMERSION_MODE = stringPreferencesKey("immersion_mode")
        val BACKGROUND_PARALLAX = booleanPreferencesKey("background_parallax")
        val REDUCE_MOTION = booleanPreferencesKey("reduce_motion")
    }
}
