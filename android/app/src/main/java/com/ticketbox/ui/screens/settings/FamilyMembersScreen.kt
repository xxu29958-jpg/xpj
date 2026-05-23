package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.domain.model.LedgerAuditEntry
import com.ticketbox.domain.model.ledgerAuditActionLabel
import com.ticketbox.domain.model.ledgerAuditResultLabel
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.AppGlassCard
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
    val state by viewModel.uiState.collectAsState()
    var pendingAction by remember { mutableStateOf<FamilyMemberAction?>(null) }
    val canManageMembers = currentRole == LEDGER_ROLE_OWNER && viewModel.deviceIsOwner()

    LaunchedEffect(activeLedgerId) {
        viewModel.refresh(activeLedgerId, currentRole)
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
        title = "家庭成员",
        subtitle = if (canManageMembers) {
            "管理当前账本成员、角色和拥有者。"
        } else {
            "查看当前账本成员和权限状态。只有拥有者能管理成员。"
        },
        onBack = onBack,
    ) {
        SettingsSection(title = "当前账本成员", icon = Icons.Filled.Group) {
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
                ) {
                    if (state.members.isEmpty() && state.loading) {
                        Column(modifier = Modifier.shimmer()) {
                            repeat(3) { ListItemSkeleton(horizontalPadding = 0.dp) }
                        }
                    } else if (state.members.isEmpty()) {
                        Text(
                            text = "还没有可显示的成员。",
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
                                "刷新中…"
                            } else if (canManageMembers) {
                                "刷新成员和记录"
                            } else {
                                "刷新成员"
                            },
                        )
                    }
                }
            }
        }
        if (canManageMembers) {
            SettingsSection(title = "成员记录", icon = Icons.Filled.Info) {
                AppGlassCard(containerAlpha = 0.96f) {
                    Column(
                        modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
                    ) {
                        if (state.auditItems.isEmpty() && state.auditLoading) {
                            Column(modifier = Modifier.shimmer()) {
                                repeat(3) { ListItemSkeleton(horizontalPadding = 0.dp) }
                            }
                        } else if (state.auditItems.isEmpty()) {
                            Text(
                                text = "还没有成员变更记录。",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        state.auditItems.forEach { item ->
                            LedgerAuditRow(item = item)
                        }
                        if (state.auditLoading && state.auditItems.isNotEmpty()) {
                            Text(
                                text = "正在刷新成员记录…",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }
        state.message?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.secondary,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

@Composable
private fun LedgerAuditRow(item: LedgerAuditEntry) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(4.dp),
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
            text = "操作者：${item.actorName ?: "系统"}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = "目标：${item.targetName ?: "未记录"}",
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
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
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
                        Spacer(Modifier.width(6.dp))
                        Text(
                            text = "我",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
                Text(
                    text = if (member.joinedAt.isNullOrBlank()) {
                        "加入时间：未记录"
                    } else {
                        "加入时间：${displayTime(member.joinedAt)}"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (member.isDisabled) {
                    Text(
                        text = "已停用：${displayTime(member.disabledAt)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
            Column(
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                SettingsRoleChip(role = member.role)
                Text(
                    text = if (member.isDisabled) "已停用" else "活跃",
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
                horizontalArrangement = Arrangement.spacedBy(8.dp),
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
                    Text(if (targetRole == LEDGER_ROLE_VIEWER) "改为只读" else "改为成员")
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    onClick = onTransferOwner,
                ) {
                    Text("转让拥有者")
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    onClick = onDisable,
                ) {
                    Text("停用")
                }
            }
        }
    }
}

private val FamilyMember.canBeManaged: Boolean
    get() = !isSelf && !isDisabled && role != LEDGER_ROLE_OWNER

private fun roleChangeText(item: LedgerAuditEntry): String? {
    val before = item.previousRole?.let { ledgerRoleLabel(it) }
    val after = item.newRole?.let { ledgerRoleLabel(it) }
    return when {
        before != null && after != null -> "角色：$before → $after"
        after != null -> "角色：$after"
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
            "调整成员角色？",
            "将${action.member.displayName}调整为${ledgerRoleLabel(action.targetRole)}。已有会话下次请求会立即按新角色生效。",
            "确认调整",
        )

        is FamilyMemberAction.Disable -> Triple(
            "停用成员？",
            "停用后${action.member.displayName}将不能继续访问当前账本，当前账本下的活跃会话会被吊销。",
            "确认停用",
        )

        is FamilyMemberAction.TransferOwner -> Triple(
            "转让拥有者？",
            "转让后${action.member.displayName}会成为唯一拥有者，你会降为成员。此操作会立即影响成员管理权限。",
            "确认转让",
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
                Text("取消")
            }
        },
    )
}
