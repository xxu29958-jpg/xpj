package com.ticketbox.data.local

import android.content.Context
import androidx.core.content.edit
import androidx.datastore.preferences.preferencesDataStore
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.NotificationPreferences
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow

private val Context.ticketboxBackgroundDataStore by preferencesDataStore(
    name = "ticketbox_background_settings",
)

class LocalSettingsStore(context: Context) : TicketboxSettingsStore {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("ticketbox_settings", Context.MODE_PRIVATE)
    private val backgroundStore = BackgroundSettingsDataStore(appContext.ticketboxBackgroundDataStore)

    override val backgroundSettingsFlow: Flow<BackgroundSettings> = backgroundStore.settingsFlow

    // Hot flow over active ledger id. Initialized from disk so that
    // first subscribers observe the persisted value without a race.
    private val activeLedgerIdFlow = MutableStateFlow(prefs.getString(KEY_ACTIVE_LEDGER_ID, null))

    // 币种偏好 hot flow，与 ledger id 同理：磁盘初值保证首订阅者不会错过当前值。
    private val currencyCodeFlow = MutableStateFlow(prefs.getString(KEY_CURRENCY_CODE, null))

    override fun observeActiveLedgerId(): Flow<String?> = activeLedgerIdFlow

    override fun observeCurrencyCodeKey(): Flow<String?> = currencyCodeFlow

    override fun serverUrl(): String? = prefs.getString(KEY_SERVER_URL, null)

    override fun appSkinKey(): String? = prefs.getString(KEY_APP_SKIN, null)

    override fun currencyCodeKey(): String? = prefs.getString(KEY_CURRENCY_CODE, null)

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

    override fun notificationPreferences(): NotificationPreferences =
        NotificationPreferences(
            autoCaptureEnabled = prefs.getBoolean(KEY_NOTIFY_AUTO_CAPTURE, false),
            pendingDraftReminders = prefs.getBoolean(KEY_NOTIFY_PENDING_DRAFTS, false),
            largeAmountAlerts = prefs.getBoolean(KEY_NOTIFY_LARGE_AMOUNT, false),
            recurringReminders = prefs.getBoolean(KEY_NOTIFY_RECURRING, false),
        )

    override fun saveNotificationPreferences(preferences: NotificationPreferences) {
        prefs.edit {
            putBoolean(KEY_NOTIFY_AUTO_CAPTURE, preferences.autoCaptureEnabled)
            putBoolean(KEY_NOTIFY_PENDING_DRAFTS, preferences.pendingDraftReminders)
            putBoolean(KEY_NOTIFY_LARGE_AMOUNT, preferences.largeAmountAlerts)
            putBoolean(KEY_NOTIFY_RECURRING, preferences.recurringReminders)
        }
    }

    override fun lastConfirmedSyncAt(): String? {
        val key = lastConfirmedSyncAtKey()
        prefs.getString(key, null)?.let { return it }

        val legacyValue = prefs.getString(KEY_LAST_CONFIRMED_SYNC_AT, null) ?: return null
        if (prefs.getBoolean(KEY_LAST_CONFIRMED_SYNC_AT_MIGRATED, false)) {
            return null
        }
        prefs.edit {
            putString(key, legacyValue)
            putBoolean(KEY_LAST_CONFIRMED_SYNC_AT_MIGRATED, true)
        }
        return legacyValue
    }

    override fun accountName(): String? = prefs.getString(KEY_ACCOUNT_NAME, null)

    override fun ledgerName(): String? = prefs.getString(KEY_LEDGER_NAME, null)

    override fun activeLedgerId(): String? = prefs.getString(KEY_ACTIVE_LEDGER_ID, null)

    override fun activeLedgerName(): String? = prefs.getString(KEY_ACTIVE_LEDGER_NAME, null)

    override fun availableLedgersJson(): String? = prefs.getString(KEY_AVAILABLE_LEDGERS_JSON, null)

    override fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        prefs.edit {
            putString(KEY_ACTIVE_LEDGER_ID, ledgerId)
            putString(KEY_ACTIVE_LEDGER_NAME, ledgerName)
            // Mirror legacy ledgerName field so existing screens keep working.
            putString(KEY_LEDGER_NAME, ledgerName)
        }
        activeLedgerIdFlow.value = ledgerId
    }

    override fun saveAvailableLedgersJson(json: String?) {
        prefs.edit {
            if (json.isNullOrBlank()) {
                remove(KEY_AVAILABLE_LEDGERS_JSON)
            } else {
                putString(KEY_AVAILABLE_LEDGERS_JSON, json)
            }
        }
    }

    override fun deviceName(): String? = prefs.getString(KEY_DEVICE_NAME, null)

    override fun role(): String? = prefs.getString(KEY_ROLE, null)

    override fun boundAt(): String? = prefs.getString(KEY_BOUND_AT, null)

    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        prefs.edit {
            putString(KEY_ACCOUNT_NAME, accountName)
            putString(KEY_ACTIVE_LEDGER_ID, ledgerId)
            putString(KEY_ACTIVE_LEDGER_NAME, ledgerName)
            putString(KEY_LEDGER_NAME, ledgerName)
            putString(KEY_DEVICE_NAME, deviceName)
            putString(KEY_ROLE, role)
            putString(KEY_BOUND_AT, boundAt)
        }
        activeLedgerIdFlow.value = ledgerId
    }

    override fun saveLastConfirmedSyncAt(value: String) {
        val ledgerId = activeLedgerId()?.takeIf { it.isNotBlank() } ?: LEGACY_LEDGER_ID
        saveLastConfirmedSyncAtForLedger(ledgerId, value)
    }

    override fun saveLastConfirmedSyncAtForLedger(ledgerId: String, value: String) {
        prefs.edit {
            putString(lastConfirmedSyncAtKey(ledgerId), value)
            if (ledgerId == (activeLedgerId()?.takeIf { it.isNotBlank() } ?: LEGACY_LEDGER_ID)) {
                putString(KEY_LAST_CONFIRMED_SYNC_AT, value)
            }
            putBoolean(KEY_LAST_CONFIRMED_SYNC_AT_MIGRATED, true)
        }
    }

    override fun clearLastConfirmedSyncAt() {
        prefs.edit {
            remove(lastConfirmedSyncAtKey())
            remove(KEY_LAST_CONFIRMED_SYNC_AT)
        }
    }

    override fun clearLastConfirmedSyncAtForLedger(ledgerId: String) {
        val activeLedgerId = activeLedgerId()?.takeIf { it.isNotBlank() } ?: LEGACY_LEDGER_ID
        prefs.edit {
            remove(lastConfirmedSyncAtKey(ledgerId))
            if (ledgerId == activeLedgerId) {
                remove(KEY_LAST_CONFIRMED_SYNC_AT)
            }
        }
    }

    override fun clearLedgerScopedRuntimeState() {
        prefs.edit {
            prefs.all.keys
                .filter { key ->
                    key == KEY_LAST_CONFIRMED_SYNC_AT ||
                        key == KEY_LAST_CONFIRMED_SYNC_AT_MIGRATED ||
                        key == KEY_LAST_UPLOAD_AT ||
                        key == KEY_LAST_UPLOAD_AT_MIGRATED ||
                        key.startsWith(KEY_LAST_CONFIRMED_SYNC_AT_BY_LEDGER_PREFIX) ||
                        key.startsWith(KEY_LAST_UPLOAD_AT_BY_LEDGER_PREFIX)
                }
                .forEach(::remove)
        }
    }

    override fun lastUploadAt(): String? {
        val key = lastUploadAtKey()
        prefs.getString(key, null)?.let { return it }

        val legacyValue = prefs.getString(KEY_LAST_UPLOAD_AT, null) ?: return null
        if (prefs.getBoolean(KEY_LAST_UPLOAD_AT_MIGRATED, false)) {
            return null
        }
        prefs.edit {
            putString(key, legacyValue)
            putBoolean(KEY_LAST_UPLOAD_AT_MIGRATED, true)
        }
        return legacyValue
    }

    override fun saveLastUploadAt(value: String) {
        prefs.edit {
            putString(lastUploadAtKey(), value)
            putString(KEY_LAST_UPLOAD_AT, value)
        }
    }

    override fun saveAppSkinKey(skinKey: String) {
        prefs.edit {
            putString(KEY_APP_SKIN, skinKey)
        }
    }

    override fun saveCurrencyCodeKey(currencyKey: String) {
        val sanitized = currencyKey.trim().uppercase()
        if (sanitized.isBlank()) return
        prefs.edit {
            putString(KEY_CURRENCY_CODE, sanitized)
        }
        currencyCodeFlow.value = sanitized
    }

    override fun saveServerUrl(serverUrl: String) {
        prefs.edit {
            putString(KEY_SERVER_URL, serverUrl.trim().trimEnd('/'))
        }
    }

    // Recent global-search queries persist as a newline-joined string (queries
    // are single-line so the delimiter is unambiguous). Non-secure UI sugar,
    // same as app_skin / currency — not ledger-scoped, wiped only by clear().
    override fun recentSearches(): List<String> {
        val raw = prefs.getString(KEY_RECENT_SEARCHES, null) ?: return emptyList()
        return raw.split('\n').filter { it.isNotBlank() }
    }

    override fun saveRecentSearches(queries: List<String>) {
        val sanitized = queries.map { it.trim() }.filter { it.isNotBlank() }
        prefs.edit {
            if (sanitized.isEmpty()) {
                remove(KEY_RECENT_SEARCHES)
            } else {
                putString(KEY_RECENT_SEARCHES, sanitized.joinToString("\n"))
            }
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
        activeLedgerIdFlow.value = null
        currencyCodeFlow.value = null
    }

    override suspend fun saveBackgroundSettings(settings: BackgroundSettings) {
        backgroundStore.saveBackgroundSettings(settings)
    }

    suspend fun clearBackground() {
        backgroundStore.clearBackground()
    }

    override suspend fun saveBackgroundImagePath(path: String) {
        backgroundStore.saveBackgroundImagePath(path)
    }

    override suspend fun clearBackgroundImage() {
        clearBackground()
    }

    override suspend fun setBackgroundCropMode(mode: BackgroundCropMode) {
        backgroundStore.setBackgroundCropMode(mode)
    }

    override suspend fun setImmersionMode(mode: ImmersionMode) {
        backgroundStore.setImmersionMode(mode)
    }

    override suspend fun setParallaxEnabled(enabled: Boolean) {
        backgroundStore.setParallaxEnabled(enabled)
    }

    override suspend fun setReduceMotion(enabled: Boolean) {
        backgroundStore.setReduceMotion(enabled)
    }

    private fun lastUploadAtKey(): String {
        val ledgerId = activeLedgerId()?.takeIf { it.isNotBlank() } ?: LEGACY_LEDGER_ID
        return "$KEY_LAST_UPLOAD_AT_BY_LEDGER_PREFIX$ledgerId"
    }

    private fun lastConfirmedSyncAtKey(): String {
        val ledgerId = activeLedgerId()?.takeIf { it.isNotBlank() } ?: LEGACY_LEDGER_ID
        return lastConfirmedSyncAtKey(ledgerId)
    }

    private fun lastConfirmedSyncAtKey(ledgerId: String): String {
        return "$KEY_LAST_CONFIRMED_SYNC_AT_BY_LEDGER_PREFIX$ledgerId"
    }

    private companion object {
        const val KEY_SERVER_URL = "server_url"
        const val KEY_RECENT_SEARCHES = "recent_searches"
        const val KEY_APP_SKIN = "app_skin"
        const val KEY_CURRENCY_CODE = "currency_code"
        const val KEY_MONTHLY_BUDGET_CENTS = "monthly_budget_cents"
        const val KEY_ACCOUNT_NAME = "account_name"
        const val KEY_LEDGER_NAME = "ledger_name"
        const val KEY_ACTIVE_LEDGER_ID = "active_ledger_id"
        const val KEY_ACTIVE_LEDGER_NAME = "active_ledger_name"
        const val KEY_AVAILABLE_LEDGERS_JSON = "available_ledgers_json"
        const val KEY_DEVICE_NAME = "device_name"
        const val KEY_ROLE = "role"
        const val KEY_BOUND_AT = "bound_at"
        const val KEY_LAST_CONFIRMED_SYNC_AT = "last_confirmed_sync_at"
        const val KEY_LAST_CONFIRMED_SYNC_AT_BY_LEDGER_PREFIX = "last_confirmed_sync_at_by_ledger:"
        const val KEY_LAST_CONFIRMED_SYNC_AT_MIGRATED = "last_confirmed_sync_at_migrated"
        const val KEY_LAST_UPLOAD_AT = "last_upload_at"
        const val KEY_LAST_UPLOAD_AT_BY_LEDGER_PREFIX = "last_upload_at_by_ledger:"
        const val KEY_LAST_UPLOAD_AT_MIGRATED = "last_upload_at_migrated"
        const val KEY_NOTIFY_AUTO_CAPTURE = "notify_auto_capture"
        const val KEY_NOTIFY_PENDING_DRAFTS = "notify_pending_drafts"
        const val KEY_NOTIFY_LARGE_AMOUNT = "notify_large_amount"
        const val KEY_NOTIFY_RECURRING = "notify_recurring"
        const val KEY_LAST_UNLOCKED_AT = "last_unlocked_at"
        const val KEY_LAST_BACKGROUNDED_AT = "last_backgrounded_at"
        const val NO_BUDGET = -1L
        const val LEGACY_LEDGER_ID = "legacy"
        const val LOCK_AFTER_MS = 5 * 60 * 1000L
    }
}
