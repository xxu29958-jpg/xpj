package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Group
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.SoftPanel
import com.ticketbox.ui.components.displayTime
import kotlinx.coroutines.launch

@Composable
fun FamilyMembersScreen(
    repository: LedgerRepository,
    activeLedgerId: String?,
    currentRole: String?,
    onBack: () -> Unit,
    onMembershipChanged: () -> Unit = {},
) {
    val scope = rememberCoroutineScope()
    var members by remember { mutableStateOf<List<FamilyMember>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var busyMemberId by remember { mutableStateOf<Long?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var pendingAction by remember { mutableStateOf<FamilyMemberAction?>(null) }
    val canManageMembers = currentRole == LEDGER_ROLE_OWNER

    suspend fun refresh() {
        loading = true
        message = null
        repository.refreshFamilyMembers(activeLedgerId)
            .onSuccess { members = it }
            .onFailure { message = it.message ?: "成员列表暂时打不开。" }
        loading = false
    }

    suspend fun runAction(action: FamilyMemberAction) {
        pendingAction = null
        busyMemberId = action.member.memberId
        message = null
        val result = when (action) {
            is FamilyMemberAction.ChangeRole -> repository.updateFamilyMemberRole(
                memberId = action.member.memberId,
                role = action.targetRole,
                ledgerId = activeLedgerId,
            )
                .map { "已将${action.member.displayName}设为${ledgerRoleLabel(action.targetRole)}。" }

            is FamilyMemberAction.Disable -> repository.disableFamilyMember(
                memberId = action.member.memberId,
                ledgerId = activeLedgerId,
            )
                .map { "已停用${action.member.displayName}。" }

            is FamilyMemberAction.TransferOwner -> repository.transferOwner(
                memberId = action.member.memberId,
                ledgerId = activeLedgerId,
            )
                .map { "已将拥有者转让给${action.member.displayName}。" }
        }
        result
            .onSuccess { success ->
                refresh()
                message = success
                onMembershipChanged()
            }
            .onFailure { message = it.message ?: "成员管理操作没有完成。" }
        busyMemberId = null
    }

    LaunchedEffect(activeLedgerId) {
        refresh()
    }

    pendingAction?.let { action ->
        FamilyMemberActionDialog(
            action = action,
            onConfirm = { scope.launch { runAction(action) } },
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
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    if (members.isEmpty() && !loading) {
                        Text(
                            text = "还没有可显示的成员。",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    members.forEach { member ->
                        FamilyMemberRow(
                            member = member,
                            canManageMembers = canManageMembers,
                            busy = busyMemberId == member.memberId,
                            onChangeRole = { targetRole ->
                                pendingAction = FamilyMemberAction.ChangeRole(member, targetRole)
                            },
                            onDisable = { pendingAction = FamilyMemberAction.Disable(member) },
                            onTransferOwner = { pendingAction = FamilyMemberAction.TransferOwner(member) },
                        )
                    }
                    OutlinedButton(
                        onClick = { scope.launch { refresh() } },
                        enabled = !loading && busyMemberId == null,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text(if (loading) "刷新中…" else "刷新成员") }
                }
            }
        }
        message?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.secondary,
                modifier = Modifier.padding(top = 4.dp),
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
                FamilyRoleChip(role = member.role)
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

@Composable
private fun FamilyRoleChip(role: String) {
    val (label, container, content) = when (role) {
        "owner" -> Triple(ledgerRoleLabel(role), Color(0xFFFFE2A0), Color(0xFF5A3B00))
        "member" -> Triple(ledgerRoleLabel(role), Color(0xFFC9DCFF), Color(0xFF1F3D7A))
        "viewer" -> Triple(ledgerRoleLabel(role), Color(0xFFE2E2E6), Color(0xFF40404A))
        else -> Triple(ledgerRoleLabel(role), Color(0xFFE2E2E6), Color(0xFF40404A))
    }
    Box(
        modifier = Modifier
            .background(container, RoundedCornerShape(6.dp))
            .padding(horizontal = 8.dp, vertical = 2.dp),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = content,
        )
    }
}

private val FamilyMember.canBeManaged: Boolean
    get() = !isSelf && !isDisabled && role != LEDGER_ROLE_OWNER

private sealed class FamilyMemberAction(open val member: FamilyMember) {
    data class ChangeRole(
        override val member: FamilyMember,
        val targetRole: String,
    ) : FamilyMemberAction(member)

    data class Disable(override val member: FamilyMember) : FamilyMemberAction(member)

    data class TransferOwner(override val member: FamilyMember) : FamilyMemberAction(member)
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
