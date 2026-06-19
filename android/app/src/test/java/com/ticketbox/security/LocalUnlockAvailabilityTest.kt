package com.ticketbox.security

import android.os.Build
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Decision-matrix coverage for [classifyLocalUnlockAvailability] (audit 8.1 local-
 * unlock dead-end fix). The classifier is a pure function over the two
 * [BiometricManager.canAuthenticate] results plus the running API level, so the
 * whole three-branch matrix — plus the API 28-29 device-credential caveat and the
 * "credential removed" degradation — is exercised here on the JVM without an
 * emulator.
 *
 * `BiometricManager.BIOMETRIC_SUCCESS` (= 0) and `Build.VERSION_CODES.R` (= 30) are
 * compile-time `static final int` constants, so they inline into literals in this
 * JVM unit test (no Android runtime needed).
 */
class LocalUnlockAvailabilityTest {
    private val success = BiometricManager.BIOMETRIC_SUCCESS
    private val noneEnrolled = BiometricManager.BIOMETRIC_ERROR_NONE_ENROLLED

    // --- Branch 1: a STRONG biometric is enrolled → biometric (crypto) path. ---

    @Test
    fun enrolledBiometricResolvesToBiometricRegardlessOfApiLevel() {
        for (sdk in intArrayOf(Build.VERSION_CODES.P, Build.VERSION_CODES.Q, Build.VERSION_CODES.R, 36)) {
            assertEquals(
                LocalUnlockAvailability.Biometric,
                classifyLocalUnlockAvailability(
                    biometricStrongStatus = success,
                    deviceCredentialStatus = success,
                    sdkInt = sdk,
                ),
                "sdk=$sdk with enrolled biometric should be Biometric",
            )
        }
    }

    @Test
    fun enrolledBiometricTakesPrecedenceOverDeviceCredential() {
        // Both available: biometric wins (it carries the crypto round-trip).
        assertEquals(
            LocalUnlockAvailability.Biometric,
            classifyLocalUnlockAvailability(
                biometricStrongStatus = success,
                deviceCredentialStatus = success,
                sdkInt = 36,
            ),
        )
    }

    // --- Branch 2: no biometric, device credential present, API >= 30 → device-credential prompt. ---

    @Test
    fun noBiometricButDeviceCredentialOnApi30PlusResolvesToDeviceCredential() {
        for (sdk in intArrayOf(Build.VERSION_CODES.R, Build.VERSION_CODES.S, 36)) {
            assertEquals(
                LocalUnlockAvailability.DeviceCredential,
                classifyLocalUnlockAvailability(
                    biometricStrongStatus = noneEnrolled,
                    deviceCredentialStatus = success,
                    sdkInt = sdk,
                ),
                "sdk=$sdk with only device credential should be DeviceCredential",
            )
        }
    }

    // --- API 28-29 caveat: DEVICE_CREDENTIAL is unsupported by androidx.biometric there. ---

    @Test
    fun deviceCredentialOnApiBelow30FallsBackToNone() {
        // androidx.biometric rejects DEVICE_CREDENTIAL (and the crypto combo) on
        // API <= 29, so a credential-only device there must gracefully disable, not
        // attempt an unsatisfiable prompt.
        for (sdk in intArrayOf(Build.VERSION_CODES.P, Build.VERSION_CODES.Q)) {
            assertEquals(
                LocalUnlockAvailability.None,
                classifyLocalUnlockAvailability(
                    biometricStrongStatus = noneEnrolled,
                    deviceCredentialStatus = success,
                    sdkInt = sdk,
                ),
                "sdk=$sdk device-credential-only must be None (28-29 caveat)",
            )
        }
    }

    // --- Branch 3: nothing available → graceful disable. ---

    @Test
    fun neitherBiometricNorDeviceCredentialResolvesToNone() {
        for (sdk in intArrayOf(Build.VERSION_CODES.P, Build.VERSION_CODES.Q, Build.VERSION_CODES.R, 36)) {
            assertEquals(
                LocalUnlockAvailability.None,
                classifyLocalUnlockAvailability(
                    biometricStrongStatus = noneEnrolled,
                    deviceCredentialStatus = noneEnrolled,
                    sdkInt = sdk,
                ),
                "sdk=$sdk with no biometric and no credential should be None",
            )
        }
    }

    @Test
    fun degradationCredentialRemovedFlipsApi30PlusFromDeviceCredentialToNone() {
        // "Once could unlock, then the user deleted the lock-screen credential":
        // same device + API, the only change is canAuthenticate(DEVICE_CREDENTIAL)
        // going SUCCESS → NONE_ENROLLED. The classifier must flip to None so the
        // gate disables the door instead of re-trapping the user.
        val before = classifyLocalUnlockAvailability(
            biometricStrongStatus = noneEnrolled,
            deviceCredentialStatus = success,
            sdkInt = Build.VERSION_CODES.S,
        )
        val after = classifyLocalUnlockAvailability(
            biometricStrongStatus = noneEnrolled,
            deviceCredentialStatus = noneEnrolled,
            sdkInt = Build.VERSION_CODES.S,
        )
        assertEquals(LocalUnlockAvailability.DeviceCredential, before)
        assertEquals(LocalUnlockAvailability.None, after)
    }

    @Test
    fun biometricOnlyPromptRequiresNegativeButton() {
        assertTrue(biometricPromptRequiresNegativeButton(BIOMETRIC_STRONG))
    }

    @Test
    fun deviceCredentialPromptMustNotSetNegativeButton() {
        assertFalse(biometricPromptRequiresNegativeButton(BIOMETRIC_STRONG or DEVICE_CREDENTIAL))
    }
}
