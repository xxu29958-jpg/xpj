package com.ticketbox.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.edit
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecureTokenStore(context: Context) : SessionTokenStore {
    private val prefs = context.getSharedPreferences("ticketbox_secure_token", Context.MODE_PRIVATE)

    override fun saveToken(token: String) {
        saveToken(token = token, expiresAt = null, softRefreshAfter = null)
    }

    override fun saveToken(token: String, expiresAt: String?, softRefreshAfter: String?) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateSecretKey())
        val encrypted = cipher.doFinal(token.toByteArray(StandardCharsets.UTF_8))
        prefs.edit {
            putString(KEY_IV, Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            putString(KEY_TOKEN, Base64.encodeToString(encrypted, Base64.NO_WRAP))
            putString(KEY_EXPIRES_AT, expiresAt)
            putString(KEY_SOFT_REFRESH_AFTER, softRefreshAfter)
        }
    }

    override fun getToken(): String? {
        return runCatching {
            val iv = Base64.decode(prefs.getString(KEY_IV, null) ?: return null, Base64.NO_WRAP)
            val encrypted = Base64.decode(prefs.getString(KEY_TOKEN, null) ?: return null, Base64.NO_WRAP)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateSecretKey(), GCMParameterSpec(128, iv))
            String(cipher.doFinal(encrypted), StandardCharsets.UTF_8)
        }.getOrNull()
    }

    override fun getSessionToken(): StoredSessionToken? {
        val token = getToken()?.takeIf { it.isNotBlank() } ?: return null
        return StoredSessionToken(
            token = token,
            expiresAt = prefs.getString(KEY_EXPIRES_AT, null),
            softRefreshAfter = prefs.getString(KEY_SOFT_REFRESH_AFTER, null),
        )
    }

    override fun clear() {
        prefs.edit {
            clear()
        }
    }

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

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "ticketbox_app_token"
        const val KEY_IV = "token_iv"
        const val KEY_TOKEN = "token_value"
        const val KEY_EXPIRES_AT = "token_expires_at"
        const val KEY_SOFT_REFRESH_AFTER = "token_soft_refresh_after"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}
