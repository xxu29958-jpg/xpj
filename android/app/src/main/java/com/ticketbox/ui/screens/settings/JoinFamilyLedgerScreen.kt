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
 * ViewModel-driven as of 2026-05; pre-refactor injected ``LedgerRepository``
 * into the screen body directly, which broke the Android layer rule.
 */
@Composable
fun JoinFamilyLedgerScreen(
    viewModel: JoinFamilyLedgerViewModel,
    onBack: () -> Unit,
    onAccepted: () -> Unit,
) {
    val state by viewModel.uiState.collectAsState()
    var inviteToken by remember { mutableStateOf("") }
    var accountName by remember { mutableStateOf("") }
    var deviceName by remember { mutableStateOf("") }

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
                    Text(
                        text = stringResource(
                            R.string.join_family_ledger_current_binding,
                            currentLedgerName,
                            currentAccountName,
                            currentRole,
                        ),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
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
                    OutlinedButton(
                        onClick = { viewModel.previewInvitation(inviteToken) },
                        enabled = !state.previewing && !state.submitting,
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
                        onClick = {
                            viewModel.acceptInvitation(
                                inviteToken = inviteToken,
                                accountName = accountName,
                                deviceName = deviceName,
                                onAccepted = onAccepted,
                                onConsumed = { inviteToken = "" },
                            )
                        },
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
