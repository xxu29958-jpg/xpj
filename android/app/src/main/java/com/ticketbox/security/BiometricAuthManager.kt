package com.ticketbox.security

import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity

class BiometricAuthManager(private val activity: FragmentActivity) {
    fun canAuthenticate(): Boolean {
        val authenticators = BIOMETRIC_STRONG or DEVICE_CREDENTIAL
        return BiometricManager.from(activity).canAuthenticate(authenticators) == BiometricManager.BIOMETRIC_SUCCESS
    }

    fun authenticate(onSuccess: () -> Unit, onError: (String) -> Unit) {
        val executor = ContextCompat.getMainExecutor(activity)
        val prompt = BiometricPrompt(
            activity,
            executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    onSuccess()
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    onError(errString.toString())
                }

                override fun onAuthenticationFailed() {
                    onError("验证失败，请重试。")
                }
            },
        )

        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle("解锁小票夹")
            .setSubtitle("验证后查看账单")
            .setAllowedAuthenticators(BIOMETRIC_STRONG or DEVICE_CREDENTIAL)
            .build()

        prompt.authenticate(promptInfo)
    }
}
