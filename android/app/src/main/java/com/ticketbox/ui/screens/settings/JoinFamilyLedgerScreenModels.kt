package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.viewmodel.JoinFamilyLedgerUiState

internal enum class JoinInvitationPrimaryAction {
    Preview,
    Accept,
}

internal data class JoinInvitationActionModel(
    val action: JoinInvitationPrimaryAction,
    @param:StringRes val labelRes: Int,
    val enabled: Boolean,
)

internal fun joinInvitationActionModel(
    state: JoinFamilyLedgerUiState,
    previewInputsReady: Boolean,
    identityInputsReady: Boolean,
): JoinInvitationActionModel {
    val action = if (state.preview == null) JoinInvitationPrimaryAction.Preview else JoinInvitationPrimaryAction.Accept
    val labelRes = when {
        state.previewing -> R.string.join_family_ledger_preview_loading
        state.submitting -> R.string.join_family_ledger_accept_loading
        action == JoinInvitationPrimaryAction.Preview -> R.string.join_family_ledger_preview_button
        else -> R.string.join_family_ledger_accept_button
    }
    return JoinInvitationActionModel(
        action = action,
        labelRes = labelRes,
        enabled = !state.previewing && !state.submitting && when (action) {
            JoinInvitationPrimaryAction.Preview -> previewInputsReady
            JoinInvitationPrimaryAction.Accept -> identityInputsReady
        },
    )
}

internal fun joinIdentityInputsReady(accountName: String, accountNameRequired: Boolean): Boolean =
    !accountNameRequired || accountName.isNotBlank()
