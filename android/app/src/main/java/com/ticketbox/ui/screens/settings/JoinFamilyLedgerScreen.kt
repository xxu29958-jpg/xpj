package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material.icons.outlined.MenuBook
import androidx.compose.material.icons.outlined.PersonOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.InvitationSessionTarget
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputDecorations
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.ScanQrButton
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.ledgerRoleLabelText
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ServerUrlEntryConfig
import com.ticketbox.viewmodel.JoinFamilyLedgerUiState
import com.ticketbox.viewmodel.JoinFamilyLedgerViewModel

data class JoinFamilyLedgerNavigation(
    val onBack: () -> Unit,
    val onAccepted: () -> Unit,
    val onInvitationConsumed: () -> Unit = {},
    val backLabel: String? = null,
)

/** Preview/accept stays with the retained ViewModel; foreign services continue in the browser. */
@Composable
fun JoinFamilyLedgerScreen(
    viewModel: JoinFamilyLedgerViewModel,
    navigation: JoinFamilyLedgerNavigation,
    serverUrlEntry: ServerUrlEntryConfig? = null,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val uriHandler = LocalUriHandler.current
    JoinFamilyLedgerPage(state,
        JoinCurrentBinding(viewModel.currentAccountName.asString(), viewModel.currentLedgerName.asString(),
            ledgerRoleLabelText(viewModel.currentLedgerRole), serverUrlEntry != null, navigation.backLabel), serverUrlEntry,
        JoinInvitationActions(
            onBack = { viewModel.reset(state.serverUrl); navigation.onBack() },
            onServerUrlChange = viewModel::onServerUrlChanged, onInviteChange = viewModel::onInvitationInputChanged,
            onNameChange = viewModel::onAccountNameChanged, onScan = { viewModel.consumeSharedInvitation(it) },
            onPreview = viewModel::previewCurrentInput,
            onAccept = { viewModel.acceptCurrentInvitation(navigation.onAccepted, navigation.onInvitationConsumed) },
            onContinueInBrowser = {
                if (viewModel.continueInBrowser(uriHandler::openUri)) {
                    viewModel.reset(state.serverUrl)
                    navigation.onInvitationConsumed()
                }
            },
        ))
}

internal data class JoinCurrentBinding(val account: String, val ledger: String, val role: String,
    val unbound: Boolean = false, val backLabel: String? = null)

internal data class JoinInvitationActions(
    val onBack: () -> Unit,
    val onServerUrlChange: (String) -> Unit,
    val onInviteChange: (String) -> Unit,
    val onNameChange: (String) -> Unit,
    val onScan: (String) -> Unit,
    val onPreview: () -> Unit,
    val onAccept: () -> Unit,
    val onContinueInBrowser: () -> Unit,
)

@Composable
internal fun JoinFamilyLedgerPage(
    state: JoinFamilyLedgerUiState,
    binding: JoinCurrentBinding,
    serverUrlEntry: ServerUrlEntryConfig?,
    actions: JoinInvitationActions,
) {
    LedgerSettingsPage(
        header = ManagementPageHeader(stringResource(R.string.join_family_ledger_page_title),
            stringResource(R.string.join_family_ledger_page_subtitle),
            ManagementPageChrome(backText = binding.backLabel ?: stringResource(R.string.join_family_ledger_back))),
        onBack = actions.onBack, action = joinPageAction(state, serverUrlEntry, actions),
    ) {
        AppStatusBanner(message = state.error ?: state.success,
            tone = if (state.error != null) MessageTone.Danger else MessageTone.Success)
        JoinAccessFields(state, binding, serverUrlEntry, actions)
        JoinDestinationDetails(state, binding)
        if (state.canContinueInBrowser) AppStatusBanner(
            UiText.res(R.string.join_family_ledger_foreign_server_message), MessageTone.Info)
        SettingsDataNote(stringResource(R.string.join_family_ledger_existing_title),
            stringResource(R.string.join_family_ledger_existing_body))
    }
}

@Composable
private fun joinPageAction(state: JoinFamilyLedgerUiState, serverUrlEntry: ServerUrlEntryConfig?, actions: JoinInvitationActions): SettingsPageAction {
    if (state.canContinueInBrowser) return SettingsPageAction(stringResource(R.string.join_family_ledger_continue_in_browser),
        !state.previewing && !state.submitting, actions.onContinueInBrowser)
    val model = joinInvitationActionModel(state,
        previewInputsReady = (state.sourceHost != null || state.invitationInput.isNotBlank()) &&
            (serverUrlEntry == null || state.serverUrl.isNotBlank() || state.sourceHost != null),
        identityInputsReady = joinIdentityInputsReady(state.accountName, state.accountNameRequired) &&
            state.target != InvitationSessionTarget.ForeignServer)
    return SettingsPageAction(stringResource(model.labelRes), model.enabled,
        if (model.action == JoinInvitationPrimaryAction.Preview) actions.onPreview else actions.onAccept)
}

@Composable
private fun JoinAccessFields(state: JoinFamilyLedgerUiState, binding: JoinCurrentBinding,
    serverUrlEntry: ServerUrlEntryConfig?, actions: JoinInvitationActions) {
    val enabled = !state.previewing && !state.submitting
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        if (serverUrlEntry?.showInput == true && state.sourceHost == null) SettingsDialogTextInput(
            SettingsTextInputState(stringResource(R.string.bind_server_field_url_label), state.serverUrl,
                placeholder = stringResource(R.string.bind_server_field_url_placeholder), enabled = enabled), actions.onServerUrlChange)
        if (state.sourceHost == null || (state.error != null && state.preview == null)) {
            AppTextInput(
                AppTextInputState(stringResource(R.string.join_family_ledger_field_invite_token), state.invitationInput,
                    placeholder = stringResource(R.string.join_family_ledger_invite_placeholder), enabled = enabled,
                    singleLine = false, maxLines = 2), AppTextInputActions(actions.onInviteChange),
                decorations = AppTextInputDecorations(trailingContent = { Icon(Icons.Outlined.Link, contentDescription = null) }))
        } else Text(stringResource(R.string.join_family_ledger_invitation_read), style = MaterialTheme.typography.bodyMedium)
        ScanQrButton(stringResource(R.string.qr_scan_invitation), enabled = enabled, onResult = actions.onScan)
        if (binding.unbound || state.accountNameRequired) AppTextInput(
            AppTextInputState(stringResource(R.string.join_family_ledger_field_account_name), state.accountName,
                placeholder = stringResource(R.string.join_family_ledger_name_placeholder), enabled = enabled),
            AppTextInputActions(actions.onNameChange),
            decorations = AppTextInputDecorations(trailingContent = { Icon(Icons.Outlined.Edit, contentDescription = null) }))
    }
}

@Composable
private fun JoinDestinationDetails(state: JoinFamilyLedgerUiState, binding: JoinCurrentBinding) {
    var showSource by rememberSaveable(state.sourceHost, state.serverUrl) { mutableStateOf(false) }
    var showTarget by rememberSaveable(state.preview?.ledgerName) { mutableStateOf(false) }
    var showIdentity by rememberSaveable(binding.account, binding.ledger) { mutableStateOf(false) }
    val preview = state.preview
    SettingsSection(title = stringResource(R.string.join_family_ledger_this_join)) {
        SettingsDataRow(stringResource(R.string.join_family_ledger_source_title),
            state.sourceHost ?: state.serverUrl.ifBlank { stringResource(R.string.join_family_ledger_source_pending) },
            Icons.Outlined.Dns, SettingsDataAction(stringResource(R.string.join_family_ledger_verify)), onClick = { showSource = !showSource })
        if (showSource) Text(stringResource(R.string.join_family_ledger_source_note), style = MaterialTheme.typography.bodySmall)
        SettingsDataRow(stringResource(R.string.join_family_ledger_target_title),
            if (preview == null) stringResource(R.string.join_family_ledger_preview_required)
            else "${preview.ledgerName.displayOr(stringResource(R.string.join_family_ledger_preview_ledger_unnamed))} · ${ledgerRoleLabelText(preview.role)}",
            Icons.Outlined.MenuBook, SettingsDataAction(stringResource(R.string.join_family_ledger_view)), onClick = { showTarget = !showTarget })
        if (showTarget) {
            if (preview != null) InvitationPreviewPanel(preview)
            else Text(stringResource(R.string.join_family_ledger_preview_required), style = MaterialTheme.typography.bodySmall)
        }
        JoinIdentityDetails(state, binding, showIdentity, onToggle = { showIdentity = !showIdentity })
    }
}

@Composable
private fun JoinIdentityDetails(state: JoinFamilyLedgerUiState, binding: JoinCurrentBinding, expanded: Boolean, onToggle: () -> Unit) {
    val newIdentity = binding.unbound || state.accountNameRequired
    SettingsDataRow(stringResource(R.string.join_family_ledger_identity_title),
        if (newIdentity) state.accountName.ifBlank { stringResource(R.string.join_family_ledger_name_placeholder) } else binding.account,
        Icons.Outlined.PersonOutline,
        SettingsDataAction(stringResource(if (newIdentity) R.string.join_family_ledger_identity_new else R.string.join_family_ledger_identity_keep)), onToggle)
    if (expanded) Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        if (newIdentity) Text(stringResource(R.string.join_family_ledger_identity_new_note)) else {
            Text(stringResource(R.string.join_family_ledger_use_current_identity, binding.account))
            Text("${binding.ledger} · ${binding.role}", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun InvitationPreviewPanel(preview: InvitationPreview) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(stringResource(R.string.join_family_ledger_preview_join_target,
            preview.ledgerName.displayOr(stringResource(R.string.join_family_ledger_preview_ledger_unnamed))), style = MaterialTheme.typography.titleSmall)
        Text(stringResource(R.string.join_family_ledger_preview_role, ledgerRoleLabelText(preview.role)))
        preview.expiresAt?.takeIf { it.isNotBlank() }?.let {
            Text(stringResource(R.string.join_family_ledger_preview_expires_at, displayDateTime(it)), style = MaterialTheme.typography.bodySmall)
        }
    }
}

private fun String?.displayOr(fallback: String): String = this?.takeIf { it.isNotBlank() } ?: fallback
