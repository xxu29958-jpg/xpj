package com.ticketbox.data.local

import com.ticketbox.domain.model.BackgroundSettings
import kotlinx.coroutines.flow.Flow

interface TicketboxSettingsStore {
    val backgroundSettingsFlow: Flow<BackgroundSettings>

    fun serverUrl(): String?

    fun appSkinKey(): String?

    fun monthlyBudgetCents(): Long?

    fun saveMonthlyBudgetCents(amountCents: Long?)

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
}
