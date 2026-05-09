package com.ticketbox.data.local

import android.content.Context
import androidx.core.content.edit
import androidx.datastore.preferences.preferencesDataStore
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import kotlinx.coroutines.flow.Flow

private val Context.ticketboxBackgroundDataStore by preferencesDataStore(
    name = "ticketbox_background_settings",
)

class LocalSettingsStore(context: Context) : TicketboxSettingsStore {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("ticketbox_settings", Context.MODE_PRIVATE)
    private val backgroundStore = BackgroundSettingsDataStore(appContext.ticketboxBackgroundDataStore)

    override val backgroundSettingsFlow: Flow<BackgroundSettings> = backgroundStore.settingsFlow

    override fun serverUrl(): String? = prefs.getString(KEY_SERVER_URL, null)

    override fun appSkinKey(): String? = prefs.getString(KEY_APP_SKIN, null)

    override fun monthlyBudgetCents(): Long? {
        val value = prefs.getLong(KEY_MONTHLY_BUDGET_CENTS, NO_BUDGET)
        return value.takeIf { it > 0L }
    }

    override fun saveMonthlyBudgetCents(amountCents: Long?) {
        prefs.edit {
            if (amountCents == null || amountCents <= 0L) {
                remove(KEY_MONTHLY_BUDGET_CENTS)
            } else {
                putLong(KEY_MONTHLY_BUDGET_CENTS, amountCents)
            }
        }
    }

    override fun lastConfirmedSyncAt(): String? = prefs.getString(KEY_LAST_CONFIRMED_SYNC_AT, null)

    override fun accountName(): String? = prefs.getString(KEY_ACCOUNT_NAME, null)

    override fun ledgerName(): String? = prefs.getString(KEY_LEDGER_NAME, null)

    override fun deviceName(): String? = prefs.getString(KEY_DEVICE_NAME, null)

    override fun role(): String? = prefs.getString(KEY_ROLE, null)

    override fun boundAt(): String? = prefs.getString(KEY_BOUND_AT, null)

    override fun saveIdentity(
        accountName: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        prefs.edit {
            putString(KEY_ACCOUNT_NAME, accountName)
            putString(KEY_LEDGER_NAME, ledgerName)
            putString(KEY_DEVICE_NAME, deviceName)
            putString(KEY_ROLE, role)
            putString(KEY_BOUND_AT, boundAt)
        }
    }

    override fun saveLastConfirmedSyncAt(value: String) {
        prefs.edit {
            putString(KEY_LAST_CONFIRMED_SYNC_AT, value)
        }
    }

    override fun clearLastConfirmedSyncAt() {
        prefs.edit {
            remove(KEY_LAST_CONFIRMED_SYNC_AT)
        }
    }

    override fun lastUploadAt(): String? = prefs.getString(KEY_LAST_UPLOAD_AT, null)

    override fun saveLastUploadAt(value: String) {
        prefs.edit {
            putString(KEY_LAST_UPLOAD_AT, value)
        }
    }

    override fun saveAppSkinKey(skinKey: String) {
        prefs.edit {
            putString(KEY_APP_SKIN, skinKey)
        }
    }

    override fun saveServerUrl(serverUrl: String) {
        prefs.edit {
            putString(KEY_SERVER_URL, serverUrl.trim().trimEnd('/'))
        }
    }

    override fun isBound(): Boolean = !serverUrl().isNullOrBlank()

    override fun markUnlocked() {
        prefs.edit {
            putLong(KEY_LAST_UNLOCKED_AT, System.currentTimeMillis())
        }
    }

    override fun markBackgrounded() {
        prefs.edit {
            putLong(KEY_LAST_BACKGROUNDED_AT, System.currentTimeMillis())
        }
    }

    override fun requiresUnlock(): Boolean {
        val lastUnlockedAt = prefs.getLong(KEY_LAST_UNLOCKED_AT, 0L)
        if (lastUnlockedAt == 0L) return true
        val lastBackgroundedAt = prefs.getLong(KEY_LAST_BACKGROUNDED_AT, 0L)
        if (lastBackgroundedAt == 0L || lastBackgroundedAt <= lastUnlockedAt) return false
        return System.currentTimeMillis() - lastBackgroundedAt > LOCK_AFTER_MS
    }

    override fun clear() {
        prefs.edit {
            clear()
        }
    }

    suspend fun saveBackgroundSettings(settings: BackgroundSettings) {
        backgroundStore.saveBackgroundSettings(settings)
    }

    suspend fun clearBackground() {
        backgroundStore.clearBackground()
    }

    suspend fun saveBackgroundImagePath(path: String) {
        backgroundStore.saveBackgroundImagePath(path)
    }

    suspend fun clearBackgroundImage() {
        clearBackground()
    }

    suspend fun setBackgroundCropMode(mode: BackgroundCropMode) {
        backgroundStore.setBackgroundCropMode(mode)
    }

    suspend fun setImmersionMode(mode: ImmersionMode) {
        backgroundStore.setImmersionMode(mode)
    }

    suspend fun setParallaxEnabled(enabled: Boolean) {
        backgroundStore.setParallaxEnabled(enabled)
    }

    suspend fun setReduceMotion(enabled: Boolean) {
        backgroundStore.setReduceMotion(enabled)
    }

    private companion object {
        const val KEY_SERVER_URL = "server_url"
        const val KEY_APP_SKIN = "app_skin"
        const val KEY_MONTHLY_BUDGET_CENTS = "monthly_budget_cents"
        const val KEY_ACCOUNT_NAME = "account_name"
        const val KEY_LEDGER_NAME = "ledger_name"
        const val KEY_DEVICE_NAME = "device_name"
        const val KEY_ROLE = "role"
        const val KEY_BOUND_AT = "bound_at"
        const val KEY_LAST_CONFIRMED_SYNC_AT = "last_confirmed_sync_at"
        const val KEY_LAST_UPLOAD_AT = "last_upload_at"
        const val KEY_LAST_UNLOCKED_AT = "last_unlocked_at"
        const val KEY_LAST_BACKGROUNDED_AT = "last_backgrounded_at"
        const val NO_BUDGET = -1L
        const val LOCK_AFTER_MS = 5 * 60 * 1000L
    }
}
