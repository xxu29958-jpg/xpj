package com.ticketbox.security

import androidx.datastore.preferences.core.MutablePreferences
import androidx.datastore.preferences.core.Preferences

private const val SESSION_SCHEMA_VERSION = 3

internal data class SessionStoreSnapshot(
    val hasStateMarker: Boolean,
    val session: LocalSessionRecord?,
    val pendingDeviceEnrollment: PendingDeviceEnrollment?,
    val pendingSessionRefresh: PendingSessionRefresh?,
)

internal fun MutablePreferences.writeSession(record: LocalSessionRecord) {
    clearSessionKeys()
    this[SESSION_SCHEMA_KEY] = SESSION_SCHEMA_VERSION
    this[SESSION_GENERATION_KEY] = record.sessionGeneration
    this[SESSION_BINDING_REVISION_KEY] = record.bindingRevision
    putOrRemove(SESSION_SERVER_ID_KEY, record.serverId)
    putOrRemove(SESSION_DATA_GENERATION_KEY, record.dataGeneration)
    this[SESSION_SERVER_URL_KEY] = record.serverUrl
    putOrRemove(SESSION_ACCOUNT_PUBLIC_ID_KEY, record.identity.accountPublicId)
    putOrRemove(SESSION_DEVICE_PUBLIC_ID_KEY, record.identity.devicePublicId)
    this[SESSION_ACCOUNT_NAME_KEY] = record.identity.accountName
    this[SESSION_LEDGER_ID_KEY] = record.identity.ledgerId
    this[SESSION_LEDGER_NAME_KEY] = record.identity.ledgerName
    this[SESSION_DEVICE_NAME_KEY] = record.identity.deviceName
    this[SESSION_ROLE_KEY] = record.identity.role
    this[SESSION_BOUND_AT_KEY] = record.identity.boundAt
    writeEncryptedToken(record.credential)
}

private fun MutablePreferences.clearSessionKeys() {
    remove(SESSION_SCHEMA_KEY)
    remove(SESSION_GENERATION_KEY)
    remove(SESSION_BINDING_REVISION_KEY)
    remove(SESSION_SERVER_ID_KEY)
    remove(SESSION_DATA_GENERATION_KEY)
    remove(SESSION_SERVER_URL_KEY)
    remove(SESSION_ACCOUNT_PUBLIC_ID_KEY)
    remove(SESSION_DEVICE_PUBLIC_ID_KEY)
    remove(SESSION_ACCOUNT_NAME_KEY)
    remove(SESSION_LEDGER_ID_KEY)
    remove(SESSION_LEDGER_NAME_KEY)
    remove(SESSION_DEVICE_NAME_KEY)
    remove(SESSION_ROLE_KEY)
    remove(SESSION_BOUND_AT_KEY)
    remove(SESSION_TOKEN_IV_KEY)
    remove(SESSION_TOKEN_VALUE_KEY)
    remove(SESSION_TOKEN_EXPIRES_AT_KEY)
    remove(SESSION_TOKEN_SOFT_REFRESH_AFTER_KEY)
}

private fun MutablePreferences.writeEncryptedToken(token: StoredSessionToken) {
    val encrypted = SessionSecretCipher.encrypt(token.token)
    this[SESSION_TOKEN_IV_KEY] = encrypted.iv
    this[SESSION_TOKEN_VALUE_KEY] = encrypted.value
    putOrRemove(SESSION_TOKEN_EXPIRES_AT_KEY, token.expiresAt)
    putOrRemove(SESSION_TOKEN_SOFT_REFRESH_AFTER_KEY, token.softRefreshAfter)
}

internal fun MutablePreferences.putOrRemove(
    key: Preferences.Key<String>,
    value: String?,
) {
    if (value == null) remove(key) else this[key] = value
}

internal fun Preferences.nonBlank(key: Preferences.Key<String>): String? =
    this[key]?.takeIf { it.isNotBlank() }

internal fun Preferences.toSessionStoreSnapshot(): SessionStoreSnapshot {
    val schema = this[SESSION_SCHEMA_KEY]
    val enrollmentSchema = this[ENROLLMENT_SCHEMA_KEY]
    val refreshSchema = this[SESSION_REFRESH_SCHEMA_KEY]
    return SessionStoreSnapshot(
        hasStateMarker = schema != null || enrollmentSchema != null || refreshSchema != null,
        session = if (schema != null && schema in 1..SESSION_SCHEMA_VERSION) localSessionOrNull() else null,
        pendingDeviceEnrollment = if (enrollmentSchema == ENROLLMENT_SCHEMA_VERSION) {
            pendingDeviceEnrollmentOrNull()
        } else {
            null
        },
        pendingSessionRefresh = if (refreshSchema == SESSION_REFRESH_SCHEMA_VERSION) {
            pendingSessionRefreshOrNull()
        } else {
            null
        },
    )
}

private fun Preferences.localSessionOrNull(): LocalSessionRecord? {
    fun required(key: Preferences.Key<String>): String? = this[key]?.takeIf { it.isNotBlank() }
    val token = decryptedTokenOrNull() ?: return null
    return LocalSessionRecord(
        sessionGeneration = required(SESSION_GENERATION_KEY) ?: return null,
        bindingRevision = required(SESSION_BINDING_REVISION_KEY) ?: return null,
        serverId = this[SESSION_SERVER_ID_KEY]?.takeIf { it.isNotBlank() },
        dataGeneration = this[SESSION_DATA_GENERATION_KEY]?.takeIf { it.isNotBlank() },
        serverUrl = required(SESSION_SERVER_URL_KEY) ?: return null,
        credential = token,
        identity = LocalSessionIdentity(
            accountPublicId = this[SESSION_ACCOUNT_PUBLIC_ID_KEY]?.takeIf { it.isNotBlank() },
            devicePublicId = this[SESSION_DEVICE_PUBLIC_ID_KEY]?.takeIf { it.isNotBlank() },
            accountName = required(SESSION_ACCOUNT_NAME_KEY) ?: return null,
            ledgerId = required(SESSION_LEDGER_ID_KEY) ?: return null,
            ledgerName = required(SESSION_LEDGER_NAME_KEY) ?: return null,
            deviceName = required(SESSION_DEVICE_NAME_KEY) ?: return null,
            role = required(SESSION_ROLE_KEY) ?: return null,
            boundAt = required(SESSION_BOUND_AT_KEY) ?: return null,
        ),
    )
}

private fun Preferences.decryptedTokenOrNull(): StoredSessionToken? {
    val iv = this[SESSION_TOKEN_IV_KEY] ?: return null
    val value = this[SESSION_TOKEN_VALUE_KEY] ?: return null
    val token = SessionSecretCipher.decrypt(iv, value)?.takeIf { it.isNotBlank() } ?: return null
    return StoredSessionToken(
        token = token,
        expiresAt = this[SESSION_TOKEN_EXPIRES_AT_KEY],
        softRefreshAfter = this[SESSION_TOKEN_SOFT_REFRESH_AFTER_KEY],
    )
}
