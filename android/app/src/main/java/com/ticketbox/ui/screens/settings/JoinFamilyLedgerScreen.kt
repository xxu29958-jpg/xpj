package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppGlassCard
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
 * [serverUrlEntry] = null (historic behaviour); the cold-start「我有家庭邀请」
 * entry mounts it unbound with a non-null [serverUrlEntry] — the screen then
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
    val state by viewModel.uiState.collectAsState()
    var inviteToken by remember { mutableStateOf("") }
    var accountName by remember { mutableStateOf("") }
    var deviceName by remember { mutableStateOf("") }
    var serverUrl by remember(serverUrlEntry) { mutableStateOf(serverUrlEntry?.defaultUrl.orEmpty()) }

    val currentAccountName = viewModel.currentAccountName.asString()
    val currentLedgerName = viewModel.currentLedgerName.asString()
    val currentRole = ledgerRoleLabel(viewModel.currentLedgerRole)

    SettingsPageFrame(
        title = stringResource(R.string.join_family_ledger_page_title),
        subtitle = stringResource(R.string.join_family_ledger_page_subtitle),
        onBack = onBack,
    ) {
        SettingsSection(
            title = stringResource(R.string.join_family_ledger_section_invite),
            icon = Icons.Filled.GroupAdd,
        ) {
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                ) {
                    if (serverUrlEntry == null) {
                        Text(
                            text = stringResource(
                                R.string.join_family_ledger_current_binding,
                                currentLedgerName,
                                currentAccountName,
                                currentRole,
                            ),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (serverUrlEntry?.showInput == true) {
                        OutlinedTextField(
                            value = serverUrl,
                            onValueChange = { value ->
                                serverUrl = value
                                viewModel.onServerUrlChanged()
                            },
                            label = { Text(stringResource(R.string.bind_server_field_url_label)) },
                            placeholder = { Text(stringResource(R.string.bind_server_field_url_placeholder)) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    OutlinedTextField(
                        value = inviteToken,
                        onValueChange = { value ->
                            inviteToken = value.take(INVITE_TOKEN_MAX)
                            viewModel.onTokenChanged()
                        },
                        label = { Text(stringResource(R.string.join_family_ledger_field_invite_token)) },
                        singleLine = false,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = accountName,
                        onValueChange = { value -> accountName = value.take(NAME_MAX) },
                        label = { Text(stringResource(R.string.join_family_ledger_field_account_name)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = deviceName,
                        onValueChange = { value -> deviceName = value.take(NAME_MAX) },
                        label = { Text(stringResource(R.string.join_family_ledger_field_device_name)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    JoinInvitationActions(
                        state = state,
                        previewEnabled = serverUrlEntry == null || serverUrl.isNotBlank(),
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
                    )
                }
            }
        }

        state.error?.let {
            Text(
                text = it.asString(),
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
        state.success?.let {
            Text(
                text = it.asString(),
                color = MaterialTheme.colorScheme.secondary,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

/** Preview/accept 按钮对 + 预览面板 + 「先预览」提示——从主函数抽出以守
 *  detekt CyclomaticComplexMethod(双宿主分支把主函数推过 14)。 */
@Composable
private fun JoinInvitationActions(
    state: JoinFamilyLedgerUiState,
    previewEnabled: Boolean,
    onPreview: () -> Unit,
    onAccept: () -> Unit,
) {
    OutlinedButton(
        onClick = onPreview,
        enabled = !state.previewing && !state.submitting && previewEnabled,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(
            if (state.previewing) {
                stringResource(R.string.join_family_ledger_preview_loading)
            } else {
                stringResource(R.string.join_family_ledger_preview_button)
            },
        )
    }
    state.preview?.let { InvitationPreviewPanel(preview = it) }
    Button(
        onClick = onAccept,
        enabled = !state.submitting && !state.previewing && state.preview != null,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(
            if (state.submitting) {
                stringResource(R.string.join_family_ledger_accept_loading)
            } else {
                stringResource(R.string.join_family_ledger_accept_button)
            },
        )
    }
    if (state.preview == null) {
        Text(
            text = stringResource(R.string.join_family_ledger_preview_required),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun InvitationPreviewPanel(preview: InvitationPreview) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
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
            text = stringResource(R.string.join_family_ledger_preview_role, ledgerRoleLabel(preview.role)),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        preview.expiresAt?.takeIf { it.isNotBlank() }?.let {
            Text(
                text = stringResource(R.string.join_family_ledger_preview_expires_at, it),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private fun String?.displayOr(fallback: String): String =
    this?.takeIf { it.isNotBlank() } ?: fallback
