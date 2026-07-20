package com.ticketbox.data.local

import android.content.Context

/** Read-once adapter for the pre-v1.3 binding fields in ordinary preferences. */
internal class LegacySessionProjectionPreferences(context: Context) : LegacySessionProjectionStore {
    private val prefs = context.applicationContext.getSharedPreferences(
        TICKETBOX_SETTINGS_PREFERENCES,
        Context.MODE_PRIVATE,
    )

    override fun readLegacySessionProjection(): PersistedSessionProjection? {
        val serverUrl = value(SERVER_URL) ?: return null
        return PersistedSessionProjection(
            serverUrl = serverUrl,
            identity = PersistedLedgerIdentity(
                accountName = value(ACCOUNT_NAME) ?: return null,
                ledgerId = value(ACTIVE_LEDGER_ID) ?: return null,
                ledgerName = value(ACTIVE_LEDGER_NAME) ?: value(LEDGER_NAME) ?: return null,
                deviceName = value(DEVICE_NAME) ?: return null,
                role = value(ROLE) ?: return null,
                boundAt = value(BOUND_AT) ?: return null,
            ),
        )
    }

    override fun clearLegacySessionProjection() {
        val editor = prefs.edit()
        LEGACY_SESSION_KEYS.forEach(editor::remove)
        check(editor.commit()) { "Unable to retire the legacy session projection." }
    }

    private fun value(key: String): String? =
        prefs.getString(key, null)?.takeIf { it.isNotBlank() }

    private companion object {
        const val SERVER_URL = "server_url"
        const val ACCOUNT_NAME = "account_name"
        const val LEDGER_NAME = "ledger_name"
        const val ACTIVE_LEDGER_ID = "active_ledger_id"
        const val ACTIVE_LEDGER_NAME = "active_ledger_name"
        const val DEVICE_NAME = "device_name"
        const val ROLE = "role"
        const val BOUND_AT = "bound_at"

        val LEGACY_SESSION_KEYS = listOf(
            SERVER_URL,
            ACCOUNT_NAME,
            LEDGER_NAME,
            ACTIVE_LEDGER_ID,
            ACTIVE_LEDGER_NAME,
            DEVICE_NAME,
            ROLE,
            BOUND_AT,
        )
    }
}
