package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow

internal fun boundSettingsStore(): FakeTicketboxSettingsStore =
    FakeTicketboxSettingsStore().apply {
        saveServerUrl("https://api.example.com")
        saveIdentity(
            accountName = "我",
            ledgerId = "owner",
            ledgerName = "我的小票夹",
            deviceName = "Pixel",
            role = "owner",
            boundAt = "2026-05-01T00:00:00Z",
        )
    }

internal class FakeTicketboxSettingsStore(
    private val events: MutableList<String> = mutableListOf(),
) : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = MutableStateFlow(BackgroundSettings())
    private var serverUrl: String? = null
    private var accountName: String? = null
    private val ledgerIdFlow = MutableStateFlow<String?>(null)
    private var ledgerName: String? = null
    private var availableLedgersJson: String? = null
    private var deviceName: String? = null
    private var role: String? = null
    private var boundAt: String? = null
    private val lastConfirmedSyncAtByLedger = mutableMapOf<String, String>()
    private var lastUploadAt: String? = null
    private var monthlyBudgetCents: Long? = null
    private var appSkinKey: String? = null
    var onSaveIdentity: (() -> Unit)? = null

    override fun serverUrl(): String? = serverUrl

    override fun appSkinKey(): String? = appSkinKey

    override fun monthlyBudgetCents(): Long? = monthlyBudgetCents

    override fun saveMonthlyBudgetCents(amountCents: Long?) {
        monthlyBudgetCents = amountCents
    }

    override fun lastConfirmedSyncAt(): String? =
        lastConfirmedSyncAtByLedger[activeLedgerId() ?: "legacy"]

    override fun accountName(): String? = accountName

    override fun ledgerName(): String? = ledgerName

    override fun activeLedgerId(): String? = ledgerIdFlow.value

    override fun activeLedgerName(): String? = ledgerName

    override fun availableLedgersJson(): String? = availableLedgersJson

    override fun observeActiveLedgerId(): Flow<String?> = ledgerIdFlow

    override fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        events += "saveActiveLedger"
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
    }

    override fun saveAvailableLedgersJson(json: String?) {
        availableLedgersJson = json
    }

    override fun deviceName(): String? = deviceName

    override fun role(): String? = role

    override fun boundAt(): String? = boundAt

    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        events += "saveIdentity"
        this.accountName = accountName
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
        this.deviceName = deviceName
        this.role = role
        this.boundAt = boundAt
        onSaveIdentity?.invoke()
    }

    override fun saveLastConfirmedSyncAt(value: String) {
        saveLastConfirmedSyncAtForLedger(activeLedgerId() ?: "legacy", value)
    }

    override fun saveLastConfirmedSyncAtForLedger(ledgerId: String, value: String) {
        lastConfirmedSyncAtByLedger[ledgerId] = value
    }

    override fun clearLastConfirmedSyncAt() {
        lastConfirmedSyncAtByLedger.remove(activeLedgerId() ?: "legacy")
    }

    override fun clearLastConfirmedSyncAtForLedger(ledgerId: String) {
        events += "clearLastConfirmedSyncAtForLedger:$ledgerId"
        lastConfirmedSyncAtByLedger.remove(ledgerId)
    }

    override fun clearLedgerScopedRuntimeState() {
        events += "clearLedgerScopedRuntimeState"
        lastConfirmedSyncAtByLedger.clear()
        lastUploadAt = null
    }

    override fun lastUploadAt(): String? = lastUploadAt

    override fun saveLastUploadAt(value: String) {
        lastUploadAt = value
    }

    override fun saveAppSkinKey(skinKey: String) {
        appSkinKey = skinKey
    }

    override fun currencyCodeKey(): String? = null

    override fun saveCurrencyCodeKey(currencyKey: String) = Unit

    override fun observeCurrencyCodeKey(): Flow<String?> = MutableStateFlow(null)

    override fun saveServerUrl(serverUrl: String) {
        events += "saveServerUrl"
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }

    override fun isBound(): Boolean = !serverUrl.isNullOrBlank()

    override fun markUnlocked() = Unit

    override fun markBackgrounded() = Unit

    override fun requiresUnlock(): Boolean = false

    override fun clear() {
        serverUrl = null
        accountName = null
        ledgerIdFlow.value = null
        ledgerName = null
        deviceName = null
        role = null
        boundAt = null
        lastConfirmedSyncAtByLedger.clear()
        lastUploadAt = null
    }
}

internal class FakeSessionTokenStore(
    private val events: MutableList<String> = mutableListOf(),
) : SessionTokenStore {
    private var token: String? = null

    override fun saveToken(token: String) {
        events += "saveToken"
        this.token = token
    }

    override fun getToken(): String? = token

    override fun clear() {
        token = null
    }
}
