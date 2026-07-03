package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.annotation.StringRes
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ServerUrlEntryConfig
import com.ticketbox.viewmodel.JoinFamilyLedgerUiState
import com.ticketbox.viewmodel.JoinFamilyLedgerViewModel

private const val INVITE_TOKEN_MAX = 128
private const val NAME_MAX = 120

/**
 * v0.4-beta1: accept a family-ledger invitation on this device.
 *
 * The plain invite token is generated server-side (Owner Console) and shown
 * **once** to the inviter. The accepting device pastes it here together with
 * a fresh display name and device name; the server creates a brand-new
 * Account + Device + LedgerMember row and issues a session token that
 * replaces the current binding. The active ledger is switched to the joined
 * one as part of acceptance.
 *
 * Trust model: this screen never persists the plain token. We hold it only
 * for the duration of the request; on success the only persisted material
 * is the freshly minted session token returned by the server.
 *
 * Dual-host: the settings tree mounts it on a bound device with
 * [serverUrlEntry] = null (historic behaviour); the cold-start invitation
 * entry mounts it unbound with a non-null [serverUrlEntry] so the screen then
 * collects (or silently defaults) the server URL and routes preview through
 * it, while the current-binding line is hidden because there is no binding.
 *
 * ViewModel-driven as of 2026-05; pre-refactor injected ``LedgerRepository``
 * into the screen body directly, which broke the Android layer rule.
 */
@Composable
fun JoinFamilyLedgerScreen(
    viewModel: JoinFamilyLedgerViewModel,
    onBack: () -> Unit,
    onAccepted: () -> Unit,
    serverUrlEntry: ServerUrlEntryConfig? = null,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var inviteToken by remember { mutableStateOf("") }
    var accountName by remember { mutableStateOf("") }
    var deviceName by remember { mutableStateOf("") }
    var serverUrl by remember(serverUrlEntry) { mutableStateOf(serverUrlEntry?.defaultUrl.orEmpty()) }

    val currentAccountName = viewModel.currentAccountName.asString()
    val currentLedgerName = viewModel.currentLedgerName.asString()
    val currentRole = stringResource(ledgerRoleLabelRes(viewModel.currentLedgerRole))
    val statusMessage = state.error ?: state.success
    val statusTone = if (state.error != null) MessageTone.Danger else MessageTone.Success

    SettingsPageFrame(
        title = stringResource(R.string.join_family_ledger_page_title),
        subtitle = stringResource(R.string.join_family_ledger_page_subtitle),
        onBack = onBack,
        status = {
            AppStatusBanner(message = statusMessage, tone = statusTone)
        },
    ) {
        if (serverUrlEntry == null) {
            CurrentBindingSection(
                ledgerName = currentLedgerName,
                accountName = currentAccountName,
                role = currentRole,
            )
        }
        JoinInvitationForm(
            state = state,
            serverUrlEntry = serverUrlEntry,
            fields = JoinInvitationFormFields(
                serverUrl = serverUrl,
                inviteToken = inviteToken,
                accountName = accountName,
                deviceName = deviceName,
            ),
            actions = JoinInvitationFormActions(
                onServerUrlChange = { value ->
                    serverUrl = value
                    viewModel.onServerUrlChanged()
                },
                onInviteTokenChange = { value ->
                    inviteToken = value.take(INVITE_TOKEN_MAX)
                    viewModel.onTokenChanged()
                },
                onAccountNameChange = { value -> accountName = value.take(NAME_MAX) },
                onDeviceNameChange = { value -> deviceName = value.take(NAME_MAX) },
                onPreview = {
                    viewModel.previewInvitation(
                        inviteToken = inviteToken,
                        serverUrlOverride = if (serverUrlEntry != null) serverUrl else null,
                    )
                },
                onAccept = {
                    viewModel.acceptInvitation(
                        inviteToken = inviteToken,
                        accountName = accountName,
                        deviceName = deviceName,
                        onAccepted = onAccepted,
                        onConsumed = { inviteToken = "" },
                    )
                },
            ),
        )
    }
}

private data class JoinInvitationFormFields(
    val serverUrl: String,
    val inviteToken: String,
    val accountName: String,
    val deviceName: String,
)

private data class JoinInvitationFormActions(
    val onServerUrlChange: (String) -> Unit,
    val onInviteTokenChange: (String) -> Unit,
    val onAccountNameChange: (String) -> Unit,
    val onDeviceNameChange: (String) -> Unit,
    val onPreview: () -> Unit,
    val onAccept: () -> Unit,
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
            state.preview?.let { InvitationPreviewPanel(preview = it) }
            if (state.preview == null) {
                Text(
                    text = stringResource(R.string.join_family_ledger_preview_required),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            } else {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
                Text(
                    text = stringResource(R.string.join_family_ledger_identity_title),
                    style = MaterialTheme.typography.titleSmall,
                )
                JoinIdentityFields(state = state, fields = fields, actions = actions)
            }
            JoinInvitationActions(
                state = state,
                previewEnabled = fields.inviteToken.isNotBlank() &&
                    (serverUrlEntry == null || fields.serverUrl.isNotBlank()),
                onPreview = actions.onPreview,
                onAccept = actions.onAccept,
            )
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
    if (serverUrlEntry?.showInput == true) {
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
    SettingsDialogTextInput(
        state = SettingsTextInputState(
            label = stringResource(R.string.join_family_ledger_field_device_name),
            value = fields.deviceName,
            enabled = !state.previewing && !state.submitting,
        ),
        onValueChange = actions.onDeviceNameChange,
    )
}

@Composable
private fun JoinInvitationActions(
    state: JoinFamilyLedgerUiState,
    previewEnabled: Boolean,
    onPreview: () -> Unit,
    onAccept: () -> Unit,
) {
    val previewing = state.preview == null
    val enabled = if (previewing) {
        !state.previewing && !state.submitting && previewEnabled
    } else {
        !state.submitting && !state.previewing
    }
    val label = when {
        state.previewing -> stringResource(R.string.join_family_ledger_preview_loading)
        state.submitting -> stringResource(R.string.join_family_ledger_accept_loading)
        previewing -> stringResource(R.string.join_family_ledger_preview_button)
        else -> stringResource(R.string.join_family_ledger_accept_button)
    }
    AppPrimaryButton(
        text = label,
        icon = Icons.Filled.GroupAdd,
        modifier = Modifier.fillMaxWidth(),
        enabled = enabled,
        onClick = if (previewing) onPreview else onAccept,
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
                stringResource(ledgerRoleLabelRes(preview.role)),
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

@StringRes
private fun ledgerRoleLabelRes(role: String?): Int = when (role?.trim()) {
    LEDGER_ROLE_OWNER -> R.string.join_family_ledger_role_owner
    LEDGER_ROLE_MEMBER -> R.string.join_family_ledger_role_member
    LEDGER_ROLE_VIEWER -> R.string.join_family_ledger_role_viewer
    null, "" -> R.string.join_family_ledger_role_unknown
    else -> R.string.join_family_ledger_role_unknown
}

private fun String?.displayOr(fallback: String): String =
    this?.takeIf { it.isNotBlank() } ?: fallback
