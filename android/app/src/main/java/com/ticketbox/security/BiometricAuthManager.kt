package com.ticketbox.security

import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.ticketbox.R
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/**
 * How the local-unlock gate can be satisfied on this device. Probed once before
 * the gate renders so the三分支 (audit 8.1) can be decided up front:
 *
 *  - [Biometric]: a Class-3 (STRONG) biometric is enrolled → crypto-backed prompt
 *    (unchanged behavior; the key is bound to AUTH_BIOMETRIC_STRONG).
 *  - [DeviceCredential]: no biometric, but the device has a lock-screen credential
 *    (PIN / pattern / password) that BiometricPrompt can satisfy → fall back to a
 *    non-crypto prompt with the system「使用 PIN」option. Only reachable on
 *    API ≥ 30: androidx.biometric refuses DEVICE_CREDENTIAL on API 28-29
 *    (see [classifyLocalUnlockAvailability]).
 *  - [None]: neither is available (device has no lock screen, or device-credential-
 *    only on API 28-29) → the local door is gracefully disabled rather than trapping
 *    the user on the unlock screen. Per ENGINEERING_RULES §5 the local door only
 *    unlocks local state; the server session token is the real auth, so disabling it
 *    opens no server-side hole.
 */
enum class LocalUnlockAvailability {
    Biometric,
    DeviceCredential,
    None,
}

/**
 * Pure decision for [LocalUnlockAvailability] from the two
 * [BiometricManager.canAuthenticate] results plus the running API level. Extracted
 * as a top-level function (no Activity / framework state) so the三分支 decision
 * matrix is unit-testable without an emulator.
 *
 * API-level caveat (Android docs, verified): combining DEVICE_CREDENTIAL with a
 * crypto prompt — and a DEVICE_CREDENTIAL-only prompt — are unsupported by
 * androidx.biometric on API ≤ 29; device-credential auth with a CryptoObject needs
 * API ≥ 30 (Android 11). Since [BiometricAuthManager.authenticate] binds its key to
 * a biometric and presents a CryptoObject, the device-credential fallback is only
 * offered on API ≥ 30. On API 28-29 a device-credential-only device therefore
 * resolves to [LocalUnlockAvailability.None] (graceful disable) instead of a
 * ConfirmDeviceCredential Activity flow (out of scope for this fix).
 *
 * @param biometricStrongStatus result of canAuthenticate(BIOMETRIC_STRONG)
 * @param deviceCredentialStatus result of canAuthenticate(DEVICE_CREDENTIAL)
 * @param sdkInt Build.VERSION.SDK_INT
 */
fun classifyLocalUnlockAvailability(
    biometricStrongStatus: Int,
    deviceCredentialStatus: Int,
    sdkInt: Int,
): LocalUnlockAvailability = when {
    biometricStrongStatus == BiometricManager.BIOMETRIC_SUCCESS -> LocalUnlockAvailability.Biometric
    sdkInt >= Build.VERSION_CODES.R &&
        deviceCredentialStatus == BiometricManager.BIOMETRIC_SUCCESS -> LocalUnlockAvailability.DeviceCredential
    else -> LocalUnlockAvailability.None
}

internal fun biometricPromptRequiresNegativeButton(authenticators: Int): Boolean =
    (authenticators and DEVICE_CREDENTIAL) == 0

class BiometricAuthManager(private val activity: FragmentActivity) {
    fun unlockAvailability(): LocalUnlockAvailability {
        val manager = BiometricManager.from(activity)
        return classifyLocalUnlockAvailability(
            biometricStrongStatus = manager.canAuthenticate(BIOMETRIC_STRONG),
            deviceCredentialStatus = manager.canAuthenticate(DEVICE_CREDENTIAL),
            sdkInt = Build.VERSION.SDK_INT,
        )
    }

    fun authenticate(onSuccess: () -> Unit, onError: (String) -> Unit) {
        when (unlockAvailability()) {
            LocalUnlockAvailability.Biometric -> authenticateWithCrypto(onSuccess, onError)
            LocalUnlockAvailability.DeviceCredential -> authenticateWithDeviceCredential(onSuccess, onError)
            LocalUnlockAvailability.None -> onError(activity.getString(R.string.app_unlock_no_biometric))
        }
    }

    /**
     * Class-3 biometric path: a crypto prompt whose CryptoObject must round-trip a
     * challenge through the keystore key, so a present-but-invalidated key surfaces
     * as an error instead of a false unlock.
     */
    private fun authenticateWithCrypto(onSuccess: () -> Unit, onError: (String) -> Unit) {
        val cryptoObject = runCatching { BiometricPrompt.CryptoObject(unlockCipher()) }
            .getOrElse {
                onError(activity.getString(R.string.biometric_key_unavailable))
                return
            }
        val prompt = buildPrompt(
            onSuccess = { result -> handleCryptoSuccess(result, onSuccess, onError) },
            onError = onError,
        )
        prompt.authenticate(promptInfo(BIOMETRIC_STRONG), cryptoObject)
    }

    private fun handleCryptoSuccess(
        result: BiometricPrompt.AuthenticationResult,
        onSuccess: () -> Unit,
        onError: (String) -> Unit,
    ) {
        val cipher = result.cryptoObject?.cipher
        if (cipher == null) {
            onError(activity.getString(R.string.biometric_state_invalid))
            return
        }
        runCatching { cipher.doFinal(UNLOCK_CHALLENGE) }
            .onSuccess { onSuccess() }
            .onFailure { onError(activity.getString(R.string.biometric_state_expired)) }
    }

    /**
     * Device-credential fallback (API ≥ 30 only — see [classifyLocalUnlockAvailability]).
     * No CryptoObject: device-credential auth can't carry one below API 31 and the
     * combo is rejected with one below API 30, so this path proves identity via the
     * system PIN/pattern/password prompt and unlocks local state on success. The
     * server session token remains the real auth (§5), so the absence of the crypto
     * round-trip here doesn't weaken server-side security.
     */
    private fun authenticateWithDeviceCredential(onSuccess: () -> Unit, onError: (String) -> Unit) {
        val prompt = buildPrompt(
            onSuccess = { onSuccess() },
            onError = onError,
        )
        // setNegativeButtonText() must NOT be set alongside DEVICE_CREDENTIAL (the
        // system supplies the cancel affordance); promptInfo() honors that.
        prompt.authenticate(promptInfo(BIOMETRIC_STRONG or DEVICE_CREDENTIAL))
    }

    private fun buildPrompt(
        onSuccess: (BiometricPrompt.AuthenticationResult) -> Unit,
        onError: (String) -> Unit,
    ): BiometricPrompt {
        val executor = ContextCompat.getMainExecutor(activity)
        return BiometricPrompt(
            activity,
            executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    onSuccess(result)
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    onError(errString.toString())
                }

                override fun onAuthenticationFailed() {
                    onError(activity.getString(R.string.biometric_failed))
                }
            },
        )
    }

    private fun promptInfo(authenticators: Int): BiometricPrompt.PromptInfo {
        val builder = BiometricPrompt.PromptInfo.Builder()
            .setTitle(activity.getString(R.string.biometric_prompt_title))
            .setSubtitle(activity.getString(R.string.biometric_prompt_subtitle))
            .setAllowedAuthenticators(authenticators)
        if (biometricPromptRequiresNegativeButton(authenticators)) {
            builder.setNegativeButtonText(activity.getString(R.string.common_cancel))
        }
        return builder.build()
    }

    private fun unlockCipher(): Cipher {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateSecretKey())
        return cipher
    }

    private fun getOrCreateSecretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.secretKey?.let { return it }

        val keyGenerator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        val builder = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .setUserAuthenticationRequired(true)
            .setInvalidatedByBiometricEnrollment(true)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            builder.setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
        } else {
            @Suppress("DEPRECATION")
            builder.setUserAuthenticationValidityDurationSeconds(-1)
        }
        keyGenerator.init(builder.build())
        return keyGenerator.generateKey()
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "ticketbox_local_unlock"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        val UNLOCK_CHALLENGE = "ticketbox-local-unlock".toByteArray()
    }
}
