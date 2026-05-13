package com.ticketbox.data.local

import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.NotificationPreferences
import kotlinx.coroutines.flow.Flow

interface TicketboxSettingsStore {
    val backgroundSettingsFlow: Flow<BackgroundSettings>

    fun serverUrl(): String?

    fun appSkinKey(): String?

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

    fun accountName(): String?

    fun ledgerName(): String?

    fun activeLedgerId(): String?

    fun activeLedgerName(): String?

    fun availableLedgersJson(): String?

    /**
     * Emits whenever the active ledger id changes (login, switch, clear).
     * Emits the current value on subscription.
     */
    fun observeActiveLedgerId(): Flow<String?>

    fun saveActiveLedger(ledgerId: String, ledgerName: String)

    fun saveAvailableLedgersJson(json: String?)

    fun deviceName(): String?

    fun role(): String?

    fun boundAt(): String?

    fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    )

    fun saveLastConfirmedSyncAt(value: String)

    fun clearLastConfirmedSyncAt()

    fun lastUploadAt(): String?

    fun saveLastUploadAt(value: String)

    fun saveAppSkinKey(skinKey: String)

    fun saveServerUrl(serverUrl: String)

    fun isBound(): Boolean

    fun markUnlocked()

    fun markBackgrounded()

    fun requiresUnlock(): Boolean

    fun clear()

    private fun unsupportedSettingsWrite(): Nothing =
        error("This settings store does not support writing appearance settings.")
}
