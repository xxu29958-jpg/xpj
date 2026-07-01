package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.FamilyInvitationCreated
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.domain.model.LedgerAuditEntry
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.ledgerAuditActionLabel
import com.ticketbox.domain.model.ledgerAuditResultLabel
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FamilyMemberAction
import com.ticketbox.viewmodel.FamilyMembersViewModel
import com.valentinilk.shimmer.shimmer

@Composable
fun FamilyMembersScreen(
    viewModel: FamilyMembersViewModel,
    activeLedgerId: String?,
    currentRole: String?,
    onBack: () -> Unit,
    onMembershipChanged: () -> Unit = {},
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var pendingAction by remember { mutableStateOf<FamilyMemberAction?>(null) }
    val canManageMembers = currentRole == LEDGER_ROLE_OWNER && viewModel.deviceIsOwner()

    LaunchedEffect(activeLedgerId) {
        viewModel.refresh(activeLedgerId, currentRole)
    }
    DisposableEffect(viewModel) {
        onDispose { viewModel.dismissCreatedInvite() }
    }

    pendingAction?.let { action ->
        FamilyMemberActionDialog(
            action = action,
            onConfirm = {
                viewModel.runAction(
                    action = action,
                    activeLedgerId = activeLedgerId,
                    currentRole = currentRole,
                    onMembershipChanged = onMembershipChanged,
                )
                pendingAction = null
            },
            onDismiss = { pendingAction = null },
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.family_members_page_title),
        subtitle = if (canManageMembers) {
            stringResource(R.string.family_members_page_subtitle_manage)
        } else {
            stringResource(R.string.family_members_page_subtitle_view)
        },
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = MessageTone.Neutral) },
    ) {
        SettingsSection(
            title = stringResource(R.string.family_members_section_members),
            icon = Icons.Filled.Group,
        ) {
            SettingsOpenPanel {
                if (state.members.isEmpty() && state.loading) {
                    Column(modifier = Modifier.shimmer()) {
                        repeat(3) { ListItemSkeleton(horizontalPadding = 0.dp) }
                    }
                } else if (state.members.isEmpty()) {
                    Text(
                        text = stringResource(R.string.family_members_members_empty),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                state.members.forEach { member ->
                    FamilyMemberRow(
                        member = member,
                        canManageMembers = canManageMembers,
                        busy = state.busyMemberId == member.memberId,
                        onChangeRole = { targetRole ->
                            pendingAction = FamilyMemberAction.ChangeRole(member, targetRole)
                        },
                        onDisable = { pendingAction = FamilyMemberAction.Disable(member) },
                        onTransferOwner = { pendingAction = FamilyMemberAction.TransferOwner(member) },
                    )
                }
                OutlinedButton(
                    onClick = { viewModel.refresh(activeLedgerId, currentRole) },
                    enabled = !state.loading && state.busyMemberId == null,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        if (state.loading) {
                            stringResource(R.string.family_members_refresh_loading)
                        } else if (canManageMembers) {
                            stringResource(R.string.family_members_refresh_members_and_audit)
                        } else {
                            stringResource(R.string.family_members_refresh_members)
                        },
                    )
                }
            }
        }
        if (canManageMembers) {
            InviteFamilySection(
                creating = state.inviteCreating,
                createdInvite = state.createdInvite,
                onCreate = { role -> viewModel.createInvitation(role, activeLedgerId) },
                onDismissResult = { viewModel.dismissCreatedInvite() },
            )
            SettingsSection(
                title = stringResource(R.string.family_members_section_audit),
                icon = Icons.Filled.Info,
            ) {
                SettingsOpenPanel {
                    if (state.auditItems.isEmpty() && state.auditLoading) {
                        Column(modifier = Modifier.shimmer()) {
                            repeat(3) { ListItemSkeleton(horizontalPadding = 0.dp) }
                        }
                    } else if (state.auditItems.isEmpty()) {
                        Text(
                            text = stringResource(R.string.family_members_audit_empty),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    state.auditItems.forEach { item ->
                        LedgerAuditRow(item = item)
                    }
                    if (state.auditLoading && state.auditItems.isNotEmpty()) {
                        Text(
                            text = stringResource(R.string.family_members_audit_refreshing),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

/** Owner-only invitation creation; the plaintext token is visible only once. */
@Composable
private fun InviteFamilySection(
    creating: Boolean,
    createdInvite: FamilyInvitationCreated?,
    onCreate: (String) -> Unit,
    onDismissResult: () -> Unit,
) {
    val clipboard = LocalClipboardManager.current
    SettingsSection(
        title = stringResource(R.string.family_members_section_invite),
        icon = Icons.Filled.Group,
    ) {
        SettingsOpenPanel {
            Text(
                text = stringResource(R.string.family_members_invite_intro),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            InviteRoleButtons(creating = creating, onCreate = onCreate)
            if (creating) {
                Text(
                    text = stringResource(R.string.family_members_invite_creating),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            createdInvite?.let { invite ->
                CreatedInviteResult(
                    invite = invite,
                    onCopy = { clipboard.setText(AnnotatedString(invite.inviteToken)) },
                    onDismissResult = onDismissResult,
                )
            }
        }
    }
}

@Composable
private fun InviteRoleButtons(
    creating: Boolean,
    onCreate: (String) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        OutlinedButton(
            onClick = { onCreate(LEDGER_ROLE_MEMBER) },
            enabled = !creating,
            modifier = Modifier.weight(1f),
        ) {
            Text(stringResource(R.string.family_members_invite_as_member))
        }
        OutlinedButton(
            onClick = { onCreate(LEDGER_ROLE_VIEWER) },
            enabled = !creating,
            modifier = Modifier.weight(1f),
        ) {
            Text(stringResource(R.string.family_members_invite_as_viewer))
        }
    }
}

@Composable
private fun CreatedInviteResult(
    invite: FamilyInvitationCreated,
    onCopy: () -> Unit,
    onDismissResult: () -> Unit,
) {
    Text(
        text = stringResource(
            R.string.family_members_invite_created_title,
            ledgerRoleLabel(invite.role),
        ),
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.onSurface,
    )
    Text(
        text = invite.inviteToken,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurface,
    )
    invite.expiresAt?.let { expiresAt ->
        Text(
            text = stringResource(R.string.family_members_invite_expires_at, displayTime(expiresAt)),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
    Text(
        text = stringResource(R.string.family_members_invite_once_hint),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedButton(onClick = onCopy, modifier = Modifier.weight(1f)) {
            Text(stringResource(R.string.family_members_invite_copy))
        }
        TextButton(onClick = onDismissResult) {
            Text(stringResource(R.string.family_members_invite_dismiss))
        }
    }
}

@Composable
private fun LedgerAuditRow(item: LedgerAuditEntry) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = ledgerAuditActionLabel(item.action),
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = ledgerAuditResultLabel(item.result),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.secondary,
            )
        }
        Text(
            text = displayTime(item.createdAt),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = stringResource(
                R.string.family_members_audit_actor,
                item.actorName ?: stringResource(R.string.family_members_audit_actor_unknown),
            ),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = stringResource(
                R.string.family_members_audit_target,
                item.targetName ?: stringResource(R.string.family_members_audit_target_unknown),
            ),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        roleChangeText(item)?.let { text ->
            Text(
                text = text,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun FamilyMemberRow(
    member: FamilyMember,
    canManageMembers: Boolean,
    busy: Boolean,
    onChangeRole: (String) -> Unit,
    onDisable: () -> Unit,
    onTransferOwner: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = member.displayName,
                        style = MaterialTheme.typography.titleSmall,
                        color = if (member.isDisabled) {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        } else {
                            MaterialTheme.colorScheme.onSurface
                        },
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (member.isSelf) {
                        Spacer(Modifier.width(AppSpacing.miniGap + AppSpacing.tinyGap))
                        Text(
                            text = stringResource(R.string.family_members_row_self_badge),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
                Text(
                    text = if (member.joinedAt.isNullOrBlank()) {
                        stringResource(R.string.family_members_row_joined_unknown)
                    } else {
                        stringResource(R.string.family_members_row_joined, displayTime(member.joinedAt))
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (member.isDisabled) {
                    Text(
                        text = stringResource(R.string.family_members_row_disabled_at, displayTime(member.disabledAt)),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
            Column(
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap + AppSpacing.tinyGap),
            ) {
                SettingsRoleChip(role = member.role)
                Text(
                    text = if (member.isDisabled) {
                        stringResource(R.string.family_members_row_status_disabled)
                    } else {
                        stringResource(R.string.family_members_row_status_active)
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = if (member.isDisabled) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
        }
        if (canManageMembers && member.canBeManaged) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
            ) {
                val targetRole = if (member.role == LEDGER_ROLE_VIEWER) {
                    LEDGER_ROLE_MEMBER
                } else {
                    LEDGER_ROLE_VIEWER
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    enabled = !busy && member.role in setOf(LEDGER_ROLE_MEMBER, LEDGER_ROLE_VIEWER),
                    onClick = { onChangeRole(targetRole) },
                ) {
                    Text(
                        if (targetRole == LEDGER_ROLE_VIEWER) {
                            stringResource(R.string.family_members_action_make_viewer)
                        } else {
                            stringResource(R.string.family_members_action_make_member)
                        },
                    )
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    onClick = onTransferOwner,
                ) {
                    Text(stringResource(R.string.family_members_action_transfer_owner))
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    onClick = onDisable,
                ) {
                    Text(stringResource(R.string.family_members_action_disable))
                }
            }
        }
    }
}

private val FamilyMember.canBeManaged: Boolean
    get() = !isSelf && !isDisabled && role != LEDGER_ROLE_OWNER

@Composable
private fun roleChangeText(item: LedgerAuditEntry): String? {
    val before = item.previousRole?.let { ledgerRoleLabel(it) }
    val after = item.newRole?.let { ledgerRoleLabel(it) }
    return when {
        before != null && after != null ->
            stringResource(R.string.family_members_audit_role_change, before, after)
        after != null -> stringResource(R.string.family_members_audit_role_set, after)
        else -> null
    }
}

@Composable
private fun FamilyMemberActionDialog(
    action: FamilyMemberAction,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val (title, text, confirm) = when (action) {
        is FamilyMemberAction.ChangeRole -> Triple(
            stringResource(R.string.family_members_dialog_change_role_title),
            stringResource(
                R.string.family_members_dialog_change_role_text,
                action.member.displayName,
                ledgerRoleLabel(action.targetRole),
            ),
            stringResource(R.string.family_members_dialog_change_role_confirm),
        )

        is FamilyMemberAction.Disable -> Triple(
            stringResource(R.string.family_members_dialog_disable_title),
            stringResource(R.string.family_members_dialog_disable_text, action.member.displayName),
            stringResource(R.string.family_members_dialog_disable_confirm),
        )

        is FamilyMemberAction.TransferOwner -> Triple(
            stringResource(R.string.family_members_dialog_transfer_owner_title),
            stringResource(R.string.family_members_dialog_transfer_owner_text, action.member.displayName),
            stringResource(R.string.family_members_dialog_transfer_owner_confirm),
        )
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(confirm, color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}
