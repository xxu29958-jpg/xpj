package com.ticketbox.data.local

import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.NotificationPreferences
import kotlinx.coroutines.flow.Flow

data class PersistedLedgerIdentity(
    val accountName: String,
    val ledgerId: String,
    val ledgerName: String,
    val deviceName: String,
    val role: String,
    val boundAt: String,
)

data class PersistedSessionProjection(
    val serverUrl: String,
    val identity: PersistedLedgerIdentity,
)

/** Startup-only access to the pre-v1.3 session projection. */
internal interface LegacySessionProjectionStore {
    fun readLegacySessionProjection(): PersistedSessionProjection?

    fun clearLegacySessionProjection()
}

interface TicketboxSettingsStore {
    val backgroundSettingsFlow: Flow<BackgroundSettings>

    fun appThemeModeKey(): String?

    fun monthlyBudgetCents(): Long?

    fun saveMonthlyBudgetCents(amountCents: Long?)

    fun notificationPreferences(): NotificationPreferences = NotificationPreferences()

    fun saveNotificationPreferences(preferences: NotificationPreferences) {
        unsupportedSettingsWrite()
    }

    suspend fun saveBackgroundSettings(settings: BackgroundSettings) {
        unsupportedSettingsWrite()
    }

    suspend fun saveBackgroundImagePath(path: String) {
        unsupportedSettingsWrite()
    }

    suspend fun clearBackgroundImage() {
        unsupportedSettingsWrite()
    }

    suspend fun setBackgroundCropMode(mode: BackgroundCropMode) {
        unsupportedSettingsWrite()
    }

    suspend fun setImmersionMode(mode: ImmersionMode) {
        unsupportedSettingsWrite()
    }

    suspend fun setParallaxEnabled(enabled: Boolean) {
        unsupportedSettingsWrite()
    }

    suspend fun setReduceMotion(enabled: Boolean) {
        unsupportedSettingsWrite()
    }

    fun lastConfirmedSyncAt(): String?

    fun lastConfirmedSyncAtForLedger(ledgerId: String): String? = lastConfirmedSyncAt()

    fun availableLedgersJson(): String?

    fun saveAvailableLedgersJson(json: String?)

    fun saveLastConfirmedSyncAt(value: String)

    fun saveLastConfirmedSyncAtForLedger(ledgerId: String, value: String) {
        saveLastConfirmedSyncAt(value)
    }

    fun clearLastConfirmedSyncAt()

    fun clearLastConfirmedSyncAtForLedger(ledgerId: String)

    fun clearLedgerScopedRuntimeState()

    fun lastUploadAt(): String?

    fun lastUploadAtForLedger(ledgerId: String): String? = lastUploadAt()

    fun saveLastUploadAt(value: String)

    fun saveLastUploadAtForLedger(ledgerId: String, value: String) {
        saveLastUploadAt(value)
    }

    fun saveAppThemeModeKey(modeKey: String)

    /**
     * 已存储的币种 storage key（如 "CNY"/"USD"）。空表示沿用默认。
     */
    fun currencyCodeKey(): String?

    fun saveCurrencyCodeKey(currencyKey: String)

    /**
     * 币种偏好变更 hot flow。订阅时立即 emit 当前值。
     */
    fun observeCurrencyCodeKey(): Flow<String?>

    /**
     * Recently committed global-search queries, most-recent-first. A non-secure
     * local convenience (like [appThemeModeKey] / budget) — never holds tokens or
     * ledger-scoped data, so it survives ledger switches and is cleared only on
     * sign-out via [clear]. Default empty for stores that don't persist it.
     */
    fun recentSearches(): List<String> = emptyList()

    fun saveRecentSearches(queries: List<String>) = Unit

    fun markUnlocked()

    fun markBackgrounded()

    fun requiresUnlock(): Boolean

    fun clear()

    private fun unsupportedSettingsWrite(): Nothing =
        error("This settings store does not support writing appearance settings.")
}
