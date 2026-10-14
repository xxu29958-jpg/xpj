package com.ticketbox.ui.screens.settings

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.FamilyInvitation
import com.ticketbox.domain.model.FamilyInvitationCreated
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.shareText
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.HandoffQrCode
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.ledgerRoleLabelText
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FamilyMembersUiState
import com.ticketbox.viewmodel.FamilyMembersViewModel

@Composable
internal fun FamilyInvitationSheet(state: FamilyMembersUiState, model: FamilyMembersViewModel,
    ledgerId: String?, onDismiss: () -> Unit) {
    var role by rememberSaveable(ledgerId) { mutableStateOf(LEDGER_ROLE_MEMBER) }
    var note by rememberSaveable(ledgerId) { mutableStateOf("") }
    var days by rememberSaveable(ledgerId) { mutableStateOf("7") }
    var historyOpen by rememberSaveable(ledgerId) { mutableStateOf(false) }
    val busy = state.inviteCreating || state.revokingInvitationId != null
    val valid = (days.toIntOrNull() ?: 0) in 1..30 && note.trim().length <= 80
    val created = state.createdInvite
    LaunchedEffect(created) { if (historyOpen && created != null) model.refreshInvitations(ledgerId) }
    AppBusyGuardedSheet(busy, onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.family_members_section_invite), actions = {
            InvitationSheetActions(state, valid, { model.createInvitation(role, ledgerId, note, days.toInt()) }, onDismiss)
        }) {
            AppStatusBanner(state.message, state.messageTone)
            if (created == null) {
                InvitationFields(role, note, days, !busy) { newRole, newNote, newDays -> role = newRole; note = newNote; days = newDays }
            } else CreatedFamilyInvitation(created)
            Text(stringResource(R.string.family_invites_binding_hint), style = MaterialTheme.typography.bodyMedium)
            TextButton(onClick = {
                historyOpen = !historyOpen
                if (historyOpen) model.refreshInvitations(ledgerId)
            }, enabled = !busy) { Text(stringResource(R.string.family_invites_history)) }
            if (historyOpen) FamilyInvitationHistory(state, model, ledgerId)
        }
    }
}

@Composable
private fun InvitationSheetActions(state: FamilyMembersUiState, valid: Boolean, onCreate: () -> Unit, onDismiss: () -> Unit) {
    val clipboard = LocalClipboardManager.current
    val created = state.createdInvite
    val busy = state.inviteCreating || state.revokingInvitationId != null
    AppPrimaryButton(text = stringResource(when {
        created != null -> R.string.family_members_invite_copy
        state.inviteCreating -> R.string.family_members_invite_creating
        else -> R.string.family_invites_generate
    }), enabled = !busy && (created != null || valid), modifier = Modifier.fillMaxWidth(), onClick = {
        if (created != null) clipboard.setText(AnnotatedString(created.shareText)) else onCreate()
    })
    TextButton(onClick = onDismiss, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
        Text(stringResource(if (created != null) R.string.family_members_invite_dismiss else R.string.common_cancel))
    }
}

@Composable
private fun InvitationFields(role: String, note: String, days: String, enabled: Boolean,
    onChange: (String, String, String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        listOf(LEDGER_ROLE_MEMBER, LEDGER_ROLE_VIEWER).forEach { choice ->
            FilterChip(selected = role == choice, onClick = { onChange(choice, note, days) }, enabled = enabled,
                label = { Text(stringResource(if (choice == LEDGER_ROLE_MEMBER) R.string.family_members_invite_as_member
                    else R.string.family_members_invite_as_viewer)) })
        }
        AppTextInput(AppTextInputState(label = stringResource(R.string.family_invites_note), value = note,
            enabled = enabled, isError = note.trim().length > 80), AppTextInputActions(onValueChange = { onChange(role, it, days) }))
        AppTextInput(AppTextInputState(label = stringResource(R.string.family_invites_days), value = days,
            enabled = enabled, isError = (days.toIntOrNull() ?: 0) !in 1..30,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)), AppTextInputActions(onValueChange = { onChange(role, note, it) }))
        Text(stringResource(R.string.family_invites_limits), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun CreatedFamilyInvitation(invite: FamilyInvitationCreated) {
    val context = LocalContext.current
    val shareTitle = stringResource(R.string.family_members_invite_share_chooser)
    Text(stringResource(R.string.family_members_invite_created_title, ledgerRoleLabelText(invite.role)),
        style = MaterialTheme.typography.titleMedium)
    invite.expiresAt?.let { Text(stringResource(R.string.family_members_invite_expires_at, displayTime(it))) }
    invite.inviteUrl?.takeIf(String::isNotBlank)?.let { HandoffQrCode(it, stringResource(R.string.qr_invitation_description)) }
    Text(stringResource(if (invite.inviteUrl.isNullOrBlank()) R.string.family_members_invite_token_fallback
        else R.string.family_members_invite_link_ready))
    Text(stringResource(R.string.family_members_invite_once_hint), style = MaterialTheme.typography.bodySmall)
    TextButton(onClick = {
        context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain")
            .putExtra(Intent.EXTRA_TEXT, invite.shareText), shareTitle))
    }) { Text(stringResource(R.string.family_members_invite_share)) }
}

@Composable
private fun FamilyInvitationHistory(state: FamilyMembersUiState, model: FamilyMembersViewModel, ledgerId: String?) {
    var targetId by rememberSaveable(ledgerId) { mutableStateOf<String?>(null) }
    AppStatusBanner(state.invitationsError, MessageTone.Danger)
    TextButton(onClick = { model.refreshInvitations(ledgerId) }, enabled = !state.invitationsLoading && state.revokingInvitationId == null) {
        Text(stringResource(if (state.invitationsLoading) R.string.family_invites_loading else R.string.family_invites_refresh))
    }
    if (state.invitationsFresh && state.invitations.isEmpty()) Text(stringResource(R.string.family_invites_empty))
    state.invitations.forEach { invitation ->
        FamilyInvitationRow(invitation, state.invitationsFresh && state.revokingInvitationId == null) { targetId = invitation.publicId }
    }
    state.invitations.firstOrNull { it.publicId == targetId }?.let { target ->
        AlertDialog(onDismissRequest = { targetId = null },
            title = { Text(stringResource(R.string.family_invites_revoke)) },
            text = { Text(stringResource(R.string.family_invites_revoke_body, target.note ?: ledgerRoleLabelText(target.role))) },
            confirmButton = { TextButton(onClick = { model.revokeInvitation(target); targetId = null },
                enabled = state.invitationsFresh && target.canRevoke && state.revokingInvitationId == null) {
                Text(stringResource(R.string.family_invites_revoke))
            } },
            dismissButton = { TextButton(onClick = { targetId = null }) { Text(stringResource(R.string.common_cancel)) } },
        )
    }
}

@Composable
private fun FamilyInvitationRow(invitation: FamilyInvitation, enabled: Boolean, onRevoke: () -> Unit) {
    SettingsEntryRow(title = invitation.note ?: ledgerRoleLabelText(invitation.role),
        subtitle = ledgerRoleLabelText(invitation.role) + " · " + stringResource(when {
            invitation.revokedAt != null -> R.string.family_invites_revoked
            invitation.usedAt != null -> R.string.family_invites_used
            invitation.canRevoke -> R.string.family_invites_available
            else -> R.string.family_invites_expired
        }), icon = R.drawable.ic_lucide_users, onClick = null)
    invitation.expiresAt?.let { Text(stringResource(R.string.family_members_invite_expires_at, displayTime(it)),
        style = MaterialTheme.typography.bodySmall) }
    val revokeDescription = stringResource(R.string.family_invites_revoke_named, invitation.note ?: ledgerRoleLabelText(invitation.role))
    if (invitation.canRevoke) TextButton(onClick = onRevoke, enabled = enabled,
        modifier = Modifier.semantics { contentDescription = revokeDescription }) {
        Text(stringResource(R.string.family_invites_revoke))
    }
}
