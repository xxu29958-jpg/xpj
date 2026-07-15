package com.ticketbox.security

import androidx.datastore.preferences.core.MutablePreferences
import androidx.datastore.preferences.core.Preferences

internal const val ENROLLMENT_SCHEMA_VERSION = 1
private const val ENROLLMENT_KIND_PAIRING = "pairing"
private const val ENROLLMENT_KIND_INVITATION = "invitation"

internal fun MutablePreferences.writeDeviceEnrollment(attempt: PendingDeviceEnrollment) {
    val source = when (val intent = attempt.intent) {
        is DeviceEnrollmentIntent.Pairing -> intent.pairingCode
        is DeviceEnrollmentIntent.Invitation -> intent.inviteToken
    }
    val encryptedSource = SessionSecretCipher.encrypt(source)
    val encryptedSecret = SessionSecretCipher.encrypt(attempt.attemptSecret)
    this[ENROLLMENT_SCHEMA_KEY] = ENROLLMENT_SCHEMA_VERSION
    this[ENROLLMENT_ATTEMPT_ID_KEY] = attempt.attemptId
    this[ENROLLMENT_KIND_KEY] = when (attempt.intent) {
        is DeviceEnrollmentIntent.Pairing -> ENROLLMENT_KIND_PAIRING
        is DeviceEnrollmentIntent.Invitation -> ENROLLMENT_KIND_INVITATION
    }
    this[ENROLLMENT_SERVER_URL_KEY] = attempt.serverUrl
    this[ENROLLMENT_SOURCE_IV_KEY] = encryptedSource.iv
    this[ENROLLMENT_SOURCE_VALUE_KEY] = encryptedSource.value
    putOrRemove(
        ENROLLMENT_ACCOUNT_NAME_KEY,
        (attempt.intent as? DeviceEnrollmentIntent.Invitation)?.accountName,
    )
    this[ENROLLMENT_DEVICE_NAME_KEY] = attempt.intent.deviceName
    this[ENROLLMENT_SECRET_IV_KEY] = encryptedSecret.iv
    this[ENROLLMENT_SECRET_VALUE_KEY] = encryptedSecret.value
    this[ENROLLMENT_CREATED_AT_KEY] = attempt.createdAt
}

internal fun MutablePreferences.clearDeviceEnrollment() {
    remove(ENROLLMENT_SCHEMA_KEY)
    remove(ENROLLMENT_ATTEMPT_ID_KEY)
    remove(ENROLLMENT_KIND_KEY)
    remove(ENROLLMENT_SERVER_URL_KEY)
    remove(ENROLLMENT_SOURCE_IV_KEY)
    remove(ENROLLMENT_SOURCE_VALUE_KEY)
    remove(ENROLLMENT_ACCOUNT_NAME_KEY)
    remove(ENROLLMENT_DEVICE_NAME_KEY)
    remove(ENROLLMENT_SECRET_IV_KEY)
    remove(ENROLLMENT_SECRET_VALUE_KEY)
    remove(ENROLLMENT_CREATED_AT_KEY)
}

internal fun Preferences.pendingDeviceEnrollmentOrNull(): PendingDeviceEnrollment? {
    val source = decryptedEnrollmentValue(
        ENROLLMENT_SOURCE_IV_KEY,
        ENROLLMENT_SOURCE_VALUE_KEY,
    ) ?: return null
    val attemptSecret = decryptedEnrollmentValue(
        ENROLLMENT_SECRET_IV_KEY,
        ENROLLMENT_SECRET_VALUE_KEY,
    ) ?: return null
    val serverUrl = nonBlank(ENROLLMENT_SERVER_URL_KEY) ?: return null
    val deviceName = nonBlank(ENROLLMENT_DEVICE_NAME_KEY) ?: return null
    val intent = enrollmentIntentOrNull(source, serverUrl, deviceName) ?: return null
    return PendingDeviceEnrollment(
        attemptId = nonBlank(ENROLLMENT_ATTEMPT_ID_KEY) ?: return null,
        intent = intent,
        attemptSecret = attemptSecret,
        createdAt = nonBlank(ENROLLMENT_CREATED_AT_KEY) ?: return null,
    )
}

private fun Preferences.decryptedEnrollmentValue(
    ivKey: Preferences.Key<String>,
    valueKey: Preferences.Key<String>,
): String? {
    val iv = nonBlank(ivKey) ?: return null
    val value = nonBlank(valueKey) ?: return null
    return SessionSecretCipher.decrypt(iv, value)?.takeIf { it.isNotBlank() }
}

private fun Preferences.enrollmentIntentOrNull(
    source: String,
    serverUrl: String,
    deviceName: String,
): DeviceEnrollmentIntent? = when (nonBlank(ENROLLMENT_KIND_KEY)) {
    ENROLLMENT_KIND_PAIRING -> DeviceEnrollmentIntent.Pairing(
        serverUrl = serverUrl,
        pairingCode = source,
        deviceName = deviceName,
    )
    ENROLLMENT_KIND_INVITATION -> DeviceEnrollmentIntent.Invitation(
        serverUrl = serverUrl,
        inviteToken = source,
        accountName = nonBlank(ENROLLMENT_ACCOUNT_NAME_KEY) ?: return null,
        deviceName = deviceName,
    )
    else -> null
}
