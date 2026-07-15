package com.ticketbox.security

import androidx.datastore.preferences.core.MutablePreferences
import androidx.datastore.preferences.core.Preferences

internal const val SESSION_REFRESH_SCHEMA_VERSION = 1

internal fun MutablePreferences.writeSessionRefresh(attempt: PendingSessionRefresh) {
    val encryptedSecret = SessionSecretCipher.encrypt(attempt.attemptSecret)
    this[SESSION_REFRESH_SCHEMA_KEY] = SESSION_REFRESH_SCHEMA_VERSION
    this[SESSION_REFRESH_ATTEMPT_ID_KEY] = attempt.attemptId
    this[SESSION_REFRESH_SECRET_IV_KEY] = encryptedSecret.iv
    this[SESSION_REFRESH_SECRET_VALUE_KEY] = encryptedSecret.value
    this[SESSION_REFRESH_GENERATION_KEY] = attempt.sessionGeneration
    this[SESSION_REFRESH_SOURCE_FINGERPRINT_KEY] = attempt.sourceTokenFingerprint
    this[SESSION_REFRESH_CREATED_AT_KEY] = attempt.createdAt
}

internal fun MutablePreferences.clearSessionRefresh() {
    remove(SESSION_REFRESH_SCHEMA_KEY)
    remove(SESSION_REFRESH_ATTEMPT_ID_KEY)
    remove(SESSION_REFRESH_SECRET_IV_KEY)
    remove(SESSION_REFRESH_SECRET_VALUE_KEY)
    remove(SESSION_REFRESH_GENERATION_KEY)
    remove(SESSION_REFRESH_SOURCE_FINGERPRINT_KEY)
    remove(SESSION_REFRESH_CREATED_AT_KEY)
}

internal fun Preferences.pendingSessionRefreshOrNull(): PendingSessionRefresh? {
    val iv = nonBlank(SESSION_REFRESH_SECRET_IV_KEY) ?: return null
    val value = nonBlank(SESSION_REFRESH_SECRET_VALUE_KEY) ?: return null
    val attemptSecret = SessionSecretCipher.decrypt(iv, value)
        ?.takeIf { it.isNotBlank() }
        ?: return null
    return PendingSessionRefresh(
        attemptId = nonBlank(SESSION_REFRESH_ATTEMPT_ID_KEY) ?: return null,
        attemptSecret = attemptSecret,
        sessionGeneration = nonBlank(SESSION_REFRESH_GENERATION_KEY) ?: return null,
        sourceTokenFingerprint = nonBlank(SESSION_REFRESH_SOURCE_FINGERPRINT_KEY) ?: return null,
        createdAt = nonBlank(SESSION_REFRESH_CREATED_AT_KEY) ?: return null,
    )
}
