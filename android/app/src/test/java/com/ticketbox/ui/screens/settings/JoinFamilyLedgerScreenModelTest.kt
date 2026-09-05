package com.ticketbox.ui.screens.settings

import com.ticketbox.R
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.viewmodel.JoinFamilyLedgerUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class JoinFamilyLedgerScreenModelTest {
    @Test
    fun previewActionRequiresTokenAndServerInput() {
        val disabled = joinInvitationActionModel(
            state = JoinFamilyLedgerUiState(),
            previewInputsReady = false,
            identityInputsReady = false,
        )
        val enabled = joinInvitationActionModel(
            state = JoinFamilyLedgerUiState(),
            previewInputsReady = true,
            identityInputsReady = false,
        )

        assertEquals(JoinInvitationPrimaryAction.Preview, disabled.action)
        assertEquals(R.string.join_family_ledger_preview_button, disabled.labelRes)
        assertFalse(disabled.enabled)
        assertTrue(enabled.enabled)
    }

    @Test
    fun acceptActionRequiresOnlyTheIdentityFieldsNeededForThisDevice() {
        val state = JoinFamilyLedgerUiState(
            preview = InvitationPreview(
                ledgerId = "L_family",
                ledgerName = "Family",
                role = "member",
                expiresAt = null,
                serverId = "srv_current",
                dataGeneration = "gen_current",
            ),
        )

        val missingIdentity = joinInvitationActionModel(
            state = state,
            previewInputsReady = true,
            identityInputsReady = joinIdentityInputsReady(accountName = "", accountNameRequired = true),
        )
        val unboundReady = joinInvitationActionModel(
            state = state,
            previewInputsReady = false,
            identityInputsReady = joinIdentityInputsReady(accountName = "New Member", accountNameRequired = true),
        )
        val boundReady = joinInvitationActionModel(
            state = state,
            previewInputsReady = false,
            identityInputsReady = joinIdentityInputsReady(accountName = "", accountNameRequired = false),
        )

        assertEquals(JoinInvitationPrimaryAction.Accept, missingIdentity.action)
        assertEquals(R.string.join_family_ledger_accept_button, missingIdentity.labelRes)
        assertFalse(missingIdentity.enabled)
        assertTrue(unboundReady.enabled)
        assertTrue(boundReady.enabled)
    }
}
