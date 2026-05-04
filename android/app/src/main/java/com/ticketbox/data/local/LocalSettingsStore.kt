package com.ticketbox.data.local

import android.content.Context
import androidx.core.content.edit

class LocalSettingsStore(context: Context) {
    private val prefs = context.getSharedPreferences("ticketbox_settings", Context.MODE_PRIVATE)

    fun serverUrl(): String? = prefs.getString(KEY_SERVER_URL, null)

    fun appSkinKey(): String? = prefs.getString(KEY_APP_SKIN, null)

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

    private companion object {
        const val KEY_SERVER_URL = "server_url"
        const val KEY_APP_SKIN = "app_skin"
        const val KEY_LAST_UNLOCKED_AT = "last_unlocked_at"
        const val KEY_LAST_BACKGROUNDED_AT = "last_backgrounded_at"
        const val LOCK_AFTER_MS = 5 * 60 * 1000L
    }
}
