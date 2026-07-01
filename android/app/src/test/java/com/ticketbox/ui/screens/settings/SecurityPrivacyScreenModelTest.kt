package com.ticketbox.ui.screens.settings

import com.ticketbox.R
import kotlin.test.Test
import kotlin.test.assertEquals

class SecurityPrivacyScreenModelTest {
    @Test
    fun infoRowsSeparateDeviceVerificationCredentialsAndBackgroundPrivacy() {
        val lockedRows = securityPrivacyInfoRows(requireLocalUnlock = true)
        val unlockedRows = securityPrivacyInfoRows(requireLocalUnlock = false)

        assertEquals(
            listOf(
                SecurityPrivacyInfoKind.LocalUnlock,
                SecurityPrivacyInfoKind.SessionCredential,
                SecurityPrivacyInfoKind.BackgroundPrivacy,
            ),
            lockedRows.map { it.kind },
        )
        assertEquals(R.string.settings_security_local_unlock_label_locked, lockedRows.first().titleRes)
        assertEquals(R.string.settings_security_local_unlock_label_unlocked, unlockedRows.first().titleRes)
    }

    @Test
    fun dangerActionsClearOfflineCopyBeforeLeavingLedger() {
        val actions = securityDangerActions()

        assertEquals(
            listOf(
                SecurityDangerActionKind.ClearOfflineCopy,
                SecurityDangerActionKind.LeaveLedger,
            ),
            actions.map { it.kind },
        )
        assertEquals(
            listOf(
                R.string.settings_security_button_clear_data,
                R.string.settings_security_button_logout,
            ),
            actions.map { it.buttonRes },
        )
    }
}
