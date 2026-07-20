package com.ticketbox.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.datastore.core.handlers.ReplaceFileCorruptionHandler
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

internal val SESSION_SCHEMA_KEY = intPreferencesKey("session_schema")
internal val SESSION_GENERATION_KEY = stringPreferencesKey("session_generation")
internal val SESSION_BINDING_REVISION_KEY = stringPreferencesKey("session_binding_revision")
internal val SESSION_SERVER_ID_KEY = stringPreferencesKey("session_server_id")
internal val SESSION_DATA_GENERATION_KEY = stringPreferencesKey("session_data_generation")
internal val SESSION_SERVER_URL_KEY = stringPreferencesKey("session_server_url")
internal val SESSION_ACCOUNT_PUBLIC_ID_KEY = stringPreferencesKey("session_account_public_id")
internal val SESSION_DEVICE_PUBLIC_ID_KEY = stringPreferencesKey("session_device_public_id")
internal val SESSION_ACCOUNT_NAME_KEY = stringPreferencesKey("session_account_name")
internal val SESSION_LEDGER_ID_KEY = stringPreferencesKey("session_ledger_id")
internal val SESSION_LEDGER_NAME_KEY = stringPreferencesKey("session_ledger_name")
internal val SESSION_DEVICE_NAME_KEY = stringPreferencesKey("session_device_name")
internal val SESSION_ROLE_KEY = stringPreferencesKey("session_role")
internal val SESSION_BOUND_AT_KEY = stringPreferencesKey("session_bound_at")
internal val SESSION_TOKEN_IV_KEY = stringPreferencesKey("token_iv")
internal val SESSION_TOKEN_VALUE_KEY = stringPreferencesKey("token_value")
internal val SESSION_TOKEN_EXPIRES_AT_KEY = stringPreferencesKey("token_expires_at")
internal val SESSION_TOKEN_SOFT_REFRESH_AFTER_KEY = stringPreferencesKey("token_soft_refresh_after")
internal val ENROLLMENT_SCHEMA_KEY = intPreferencesKey("enrollment_schema")
internal val ENROLLMENT_ATTEMPT_ID_KEY = stringPreferencesKey("enrollment_attempt_id")
internal val ENROLLMENT_KIND_KEY = stringPreferencesKey("enrollment_kind")
internal val ENROLLMENT_SERVER_URL_KEY = stringPreferencesKey("enrollment_server_url")
internal val ENROLLMENT_SOURCE_IV_KEY = stringPreferencesKey("enrollment_source_iv")
internal val ENROLLMENT_SOURCE_VALUE_KEY = stringPreferencesKey("enrollment_source_value")
internal val ENROLLMENT_ACCOUNT_NAME_KEY = stringPreferencesKey("enrollment_account_name")
internal val ENROLLMENT_DEVICE_NAME_KEY = stringPreferencesKey("enrollment_device_name")
internal val ENROLLMENT_SECRET_IV_KEY = stringPreferencesKey("enrollment_secret_iv")
internal val ENROLLMENT_SECRET_VALUE_KEY = stringPreferencesKey("enrollment_secret_value")
internal val ENROLLMENT_CREATED_AT_KEY = stringPreferencesKey("enrollment_created_at")
internal val SESSION_REFRESH_SCHEMA_KEY = intPreferencesKey("session_refresh_schema")
internal val SESSION_REFRESH_ATTEMPT_ID_KEY = stringPreferencesKey("session_refresh_attempt_id")
internal val SESSION_REFRESH_SECRET_IV_KEY = stringPreferencesKey("session_refresh_secret_iv")
internal val SESSION_REFRESH_SECRET_VALUE_KEY = stringPreferencesKey("session_refresh_secret_value")
internal val SESSION_REFRESH_GENERATION_KEY = stringPreferencesKey("session_refresh_generation")
internal val SESSION_REFRESH_SOURCE_FINGERPRINT_KEY =
    stringPreferencesKey("session_refresh_source_fingerprint")
internal val SESSION_REFRESH_CREATED_AT_KEY = stringPreferencesKey("session_refresh_created_at")

private val Context.ticketboxSecureSessionDataStore by preferencesDataStore(
    name = "ticketbox_secure_session",
    corruptionHandler = ReplaceFileCorruptionHandler { emptyPreferences() },
)

internal fun secureSessionDataStore(context: Context) =
    context.applicationContext.ticketboxSecureSessionDataStore

internal data class EncryptedSessionSecret(
    val iv: String,
    val value: String,
)

internal object SessionSecretCipher {
    fun encrypt(secret: String): EncryptedSessionSecret {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateSecretKey())
        val encrypted = cipher.doFinal(secret.toByteArray(StandardCharsets.UTF_8))
        return EncryptedSessionSecret(
            iv = Base64.encodeToString(cipher.iv, Base64.NO_WRAP),
            value = Base64.encodeToString(encrypted, Base64.NO_WRAP),
        )
    }

    fun decrypt(iv: String, value: String): String? = runCatching {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(
            Cipher.DECRYPT_MODE,
            getOrCreateSecretKey(),
            GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
        )
        val encrypted = Base64.decode(value, Base64.NO_WRAP)
        String(cipher.doFinal(encrypted), StandardCharsets.UTF_8)
    }.getOrNull()

    private fun getOrCreateSecretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.secretKey?.let { return it }

        val keyGenerator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .build()
        keyGenerator.init(spec)
        return keyGenerator.generateKey()
    }

    private const val ANDROID_KEYSTORE = "AndroidKeyStore"
    private const val KEY_ALIAS = "ticketbox_app_token"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
}

internal fun readLegacySessionToken(context: Context): StoredSessionToken? {
    val legacy = context.getSharedPreferences(LEGACY_PREFS_NAME, Context.MODE_PRIVATE)
    val iv = legacy.getString(LEGACY_IV, null)?.takeIf { it.isNotBlank() } ?: return null
    val value = legacy.getString(LEGACY_TOKEN, null)?.takeIf { it.isNotBlank() } ?: return null
    val token = SessionSecretCipher.decrypt(iv, value)?.takeIf { it.isNotBlank() } ?: return null
    return StoredSessionToken(
        token = token,
        expiresAt = legacy.getString(LEGACY_EXPIRES_AT, null),
        softRefreshAfter = legacy.getString(LEGACY_SOFT_REFRESH_AFTER, null),
    )
}

internal fun clearLegacySessionToken(context: Context) {
    val legacy = context.getSharedPreferences(LEGACY_PREFS_NAME, Context.MODE_PRIVATE)
    check(legacy.edit().clear().commit()) { "Unable to retire the legacy token store." }
}

private const val LEGACY_PREFS_NAME = "ticketbox_secure_token"
private const val LEGACY_IV = "token_iv"
private const val LEGACY_TOKEN = "token_value"
private const val LEGACY_EXPIRES_AT = "token_expires_at"
private const val LEGACY_SOFT_REFRESH_AFTER = "token_soft_refresh_after"
