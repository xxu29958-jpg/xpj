package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.ledgerRoleLabelText
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ServerUrlEntryConfig
import com.ticketbox.viewmodel.JoinFamilyLedgerUiState
import com.ticketbox.viewmodel.JoinFamilyLedgerViewModel

/** Preview and explicitly accept one family invitation without persisting its plaintext token.
 * Bound devices reuse the current member/device identity; unbound devices create an enrollment
 * from a display name and the app-provided device label. A foreign server is browser-only so the
 * existing session and outbox remain untouched. */
@Composable
fun JoinFamilyLedgerScreen(
    viewModel: JoinFamilyLedgerViewModel,
    onBack: () -> Unit,
    onAccepted: () -> Unit,
    serverUrlEntry: ServerUrlEntryConfig? = null,
    onInvitationConsumed: () -> Unit = {},
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val uriHandler = LocalUriHandler.current

    val currentAccountName = viewModel.currentAccountName.asString()
    val currentLedgerName = viewModel.currentLedgerName.asString()
    val currentRole = ledgerRoleLabelText(viewModel.currentLedgerRole)
    val statusMessage = state.error ?: state.success
    val statusTone = if (state.error != null) MessageTone.Danger else MessageTone.Success

    SettingsPageFrame(
        title = stringResource(R.string.join_family_ledger_page_title),
        subtitle = stringResource(R.string.join_family_ledger_page_subtitle),
        onBack = {
            viewModel.reset(state.serverUrl)
            onBack()
        },
        status = {
            AppStatusBanner(message = statusMessage, tone = statusTone)
        },
    ) {
        JoinInvitationForm(
            state = state,
            serverUrlEntry = serverUrlEntry,
            currentAccountName = currentAccountName,
            fields = JoinInvitationFormFields(
                serverUrl = state.serverUrl,
                inviteToken = state.invitationInput,
                accountName = state.accountName,
            ),
            actions = JoinInvitationFormActions(
                onServerUrlChange = viewModel::onServerUrlChanged,
                onInviteTokenChange = viewModel::onInvitationInputChanged,
                onAccountNameChange = viewModel::onAccountNameChanged,
                onPreview = viewModel::previewCurrentInput,
                onAccept = {
                    viewModel.acceptCurrentInvitation(
                        onAccepted = onAccepted,
                        onConsumed = onInvitationConsumed,
                    )
                },
                onContinueInBrowser = {
                    if (viewModel.continueInBrowser(uriHandler::openUri)) {
                        viewModel.reset(state.serverUrl)
                        onInvitationConsumed()
                    }
                },
            ),
        )
        if (serverUrlEntry == null) {
            CurrentBindingSection(
                ledgerName = currentLedgerName,
                accountName = currentAccountName,
                role = currentRole,
            )
        }
    }
}

private data class JoinInvitationFormFields(
    val serverUrl: String,
    val inviteToken: String,
    val accountName: String,
)

private data class JoinInvitationFormActions(
    val onServerUrlChange: (String) -> Unit,
    val onInviteTokenChange: (String) -> Unit,
    val onAccountNameChange: (String) -> Unit,
    val onPreview: () -> Unit,
    val onAccept: () -> Unit,
    val onContinueInBrowser: () -> Unit,
)

@Composable
private fun CurrentBindingSection(
    ledgerName: String,
    accountName: String,
    role: String,
) {
    SettingsSection(
        title = stringResource(R.string.join_family_ledger_section_current),
        icon = Icons.Filled.Devices,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            JoinFamilyInfoRow(label = stringResource(R.string.join_family_ledger_current_ledger), value = ledgerName)
            JoinFamilyInfoRow(label = stringResource(R.string.join_family_ledger_current_account), value = accountName)
            JoinFamilyInfoRow(label = stringResource(R.string.join_family_ledger_current_role), value = role)
        }
    }
}

@Composable
private fun JoinInvitationForm(
    state: JoinFamilyLedgerUiState,
    serverUrlEntry: ServerUrlEntryConfig?,
    currentAccountName: String,
    fields: JoinInvitationFormFields,
    actions: JoinInvitationFormActions,
) {
    SettingsSection(
        title = stringResource(R.string.join_family_ledger_section_invite),
        icon = Icons.Filled.GroupAdd,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
            JoinInvitationAccessFields(
                state = state,
                serverUrlEntry = serverUrlEntry,
                fields = fields,
                actions = actions,
            )
            JoinInvitationPreviewAndIdentity(
                state = state,
                currentAccountName = currentAccountName,
                fields = fields,
                actions = actions,
            )
            if (state.canContinueInBrowser) {
                QuietOutlinedButton(
                    text = stringResource(R.string.join_family_ledger_continue_in_browser),
                    modifier = Modifier.fillMaxWidth(),
                    onClick = actions.onContinueInBrowser,
                )
            } else {
                JoinInvitationActions(
                    state = state,
                    previewEnabled = (state.sourceHost != null || fields.inviteToken.isNotBlank()) &&
                        (serverUrlEntry == null || fields.serverUrl.isNotBlank()),
                    identityReady = joinIdentityInputsReady(fields.accountName, state.accountNameRequired) &&
                        state.target != com.ticketbox.domain.model.InvitationSessionTarget.ForeignServer,
                    onPreview = actions.onPreview,
                    onAccept = actions.onAccept,
                )
            }
        }
    }
}

@Composable
private fun JoinInvitationPreviewAndIdentity(
    state: JoinFamilyLedgerUiState,
    currentAccountName: String,
    fields: JoinInvitationFormFields,
    actions: JoinInvitationFormActions,
) {
    state.preview?.let { InvitationPreviewPanel(preview = it) }
    state.sourceHost?.let { host ->
        Text(
            text = stringResource(R.string.join_family_ledger_source_host, host),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
    when {
        state.preview == null -> Text(
            text = stringResource(R.string.join_family_ledger_preview_required),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        state.canContinueInBrowser -> AppStatusBanner(
            message = com.ticketbox.domain.model.UiText.res(
                R.string.join_family_ledger_foreign_server_message,
            ),
            tone = MessageTone.Info,
        )
        else -> {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
            Text(
                text = stringResource(R.string.join_family_ledger_identity_title),
                style = MaterialTheme.typography.titleSmall,
            )
            if (state.accountNameRequired) {
                JoinIdentityFields(state = state, fields = fields, actions = actions)
            } else {
                Text(
                    text = stringResource(
                        R.string.join_family_ledger_use_current_identity,
                        currentAccountName,
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** Keep preview-host branching out of the screen body for detekt complexity. */
@Composable
private fun JoinInvitationAccessFields(
    state: JoinFamilyLedgerUiState,
    serverUrlEntry: ServerUrlEntryConfig?,
    fields: JoinInvitationFormFields,
    actions: JoinInvitationFormActions,
) {
    if (serverUrlEntry?.showInput == true && state.sourceHost == null) {
        SettingsDialogTextInput(
            state = SettingsTextInputState(
                label = stringResource(R.string.bind_server_field_url_label),
                value = fields.serverUrl,
                placeholder = stringResource(R.string.bind_server_field_url_placeholder),
                enabled = !state.previewing && !state.submitting,
            ),
            onValueChange = actions.onServerUrlChange,
        )
    }
    if (state.sourceHost == null || (state.error != null && state.preview == null)) {
        SettingsDialogTextInput(
            state = SettingsTextInputState(
                label = stringResource(R.string.join_family_ledger_field_invite_token),
                value = fields.inviteToken,
                enabled = !state.previewing && !state.submitting,
                singleLine = false,
                minLines = 1,
                maxLines = 2,
            ),
            onValueChange = actions.onInviteTokenChange,
        )
    }
}

@Composable
private fun JoinIdentityFields(
    state: JoinFamilyLedgerUiState,
    fields: JoinInvitationFormFields,
    actions: JoinInvitationFormActions,
) {
    SettingsDialogTextInput(
        state = SettingsTextInputState(
            label = stringResource(R.string.join_family_ledger_field_account_name),
            value = fields.accountName,
            enabled = !state.previewing && !state.submitting,
        ),
        onValueChange = actions.onAccountNameChange,
    )
}

@Composable
private fun JoinInvitationActions(
    state: JoinFamilyLedgerUiState,
    previewEnabled: Boolean,
    identityReady: Boolean,
    onPreview: () -> Unit,
    onAccept: () -> Unit,
) {
    val model = joinInvitationActionModel(
        state = state,
        previewInputsReady = previewEnabled,
        identityInputsReady = identityReady,
    )
    AppPrimaryButton(
        text = stringResource(model.labelRes),
        icon = Icons.Filled.GroupAdd,
        modifier = Modifier.fillMaxWidth(),
        enabled = model.enabled,
        onClick = if (model.action == JoinInvitationPrimaryAction.Preview) onPreview else onAccept,
    )
}

@Composable
private fun InvitationPreviewPanel(preview: InvitationPreview) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            text = stringResource(
                R.string.join_family_ledger_preview_join_target,
                preview.ledgerName.displayOr(
                    stringResource(R.string.join_family_ledger_preview_ledger_unnamed),
                ),
            ),
            style = MaterialTheme.typography.titleSmall,
        )
        Text(
            text = stringResource(
                R.string.join_family_ledger_preview_role,
                ledgerRoleLabelText(preview.role),
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        preview.expiresAt?.takeIf { it.isNotBlank() }?.let {
            Text(
                text = stringResource(
                    R.string.join_family_ledger_preview_expires_at,
                    displayDateTime(it),
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun JoinFamilyInfoRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.weight(0.34f),
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
    }
}

private fun String?.displayOr(fallback: String): String =
    this?.takeIf { it.isNotBlank() } ?: fallback
