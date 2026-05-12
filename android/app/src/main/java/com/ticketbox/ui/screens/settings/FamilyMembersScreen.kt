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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
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
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.SoftPanel
import com.ticketbox.ui.components.displayTime
import kotlinx.coroutines.launch

@Composable
fun FamilyMembersScreen(
    repository: LedgerRepository,
    activeLedgerId: String?,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var members by remember { mutableStateOf<List<FamilyMember>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }

    suspend fun refresh() {
        loading = true
        message = null
        repository.refreshFamilyMembers(activeLedgerId)
            .onSuccess { members = it }
            .onFailure { message = it.message ?: "成员列表暂时打不开。" }
        loading = false
    }

    LaunchedEffect(activeLedgerId) {
        refresh()
    }

    SettingsPageFrame(
        title = "家庭成员",
        subtitle = "查看当前账本成员和权限状态。",
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
                        FamilyMemberRow(member = member)
                    }
                    OutlinedButton(
                        onClick = { scope.launch { refresh() } },
                        enabled = !loading,
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
private fun FamilyMemberRow(member: FamilyMember) {
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
