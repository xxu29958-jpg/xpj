package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.SoftPanel
import kotlinx.coroutines.launch

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
 */
@Composable
fun JoinFamilyLedgerScreen(
    repository: LedgerRepository,
    onBack: () -> Unit,
    onAccepted: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var inviteToken by remember { mutableStateOf("") }
    var accountName by remember { mutableStateOf("") }
    var deviceName by remember { mutableStateOf("") }
    var preview by remember { mutableStateOf<InvitationPreview?>(null) }
    var previewing by remember { mutableStateOf(false) }
    var submitting by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var success by remember { mutableStateOf<String?>(null) }
    val currentAccountName = remember(repository) { repository.currentAccountName().displayOr("未绑定") }
    val currentLedgerName = remember(repository) { repository.currentLedgerName().displayOr("未绑定") }
    val currentRole = remember(repository) { ledgerRoleLabel(repository.currentLedgerRole()) }

    SettingsPageFrame(
        title = "加入家庭账本",
        subtitle = "先确认邀请目标，再替换本机绑定。",
        onBack = onBack,
    ) {
        SettingsSection(title = "邀请信息", icon = Icons.Filled.GroupAdd) {
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        text = "当前绑定：$currentLedgerName / $currentAccountName / $currentRole",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    OutlinedTextField(
                        value = inviteToken,
                        onValueChange = { value ->
                            inviteToken = value.take(INVITE_TOKEN_MAX)
                            preview = null
                            success = null
                        },
                        label = { Text("邀请明文") },
                        singleLine = false,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = accountName,
                        onValueChange = { value ->
                            accountName = value.take(NAME_MAX)
                        },
                        label = { Text("你的显示名") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = deviceName,
                        onValueChange = { value ->
                            deviceName = value.take(NAME_MAX)
                        },
                        label = { Text("设备名") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedButton(
                        onClick = {
                            if (previewing || submitting) return@OutlinedButton
                            error = null
                            success = null
                            scope.launch {
                                previewing = true
                                repository.previewInvitation(inviteToken)
                                    .onSuccess { preview = it }
                                    .onFailure {
                                        preview = null
                                        error = it.message ?: "预览邀请失败。"
                                    }
                                previewing = false
                            }
                        },
                        enabled = !previewing && !submitting,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text(if (previewing) "预览中…" else "预览邀请") }
                    preview?.let { InvitationPreviewPanel(preview = it) }
                    Button(
                        onClick = {
                            if (submitting) return@Button
                            val acceptedPreview = preview ?: return@Button
                            error = null
                            success = null
                            scope.launch {
                                submitting = true
                                repository.acceptInvitation(
                                    inviteToken = inviteToken,
                                    accountName = accountName,
                                    deviceName = deviceName,
                                ).onSuccess { ledger ->
                                    success = "已加入“${ledger.name}”，当前角色：${ledger.role}"
                                    // Clear the plain token from memory once consumed.
                                    inviteToken = ""
                                    preview = null
                                    onAccepted()
                                }.onFailure {
                                    preview = acceptedPreview
                                    error = it.message ?: "接受邀请失败。"
                                }
                                submitting = false
                            }
                        },
                        enabled = !submitting && !previewing && preview != null,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text(if (submitting) "处理中…" else "接受邀请") }
                    if (preview == null) {
                        Text(
                            text = "预览后才可以接受邀请；接受成功会替换本机当前绑定。",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }

        error?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
        success?.let {
            Text(
                text = it,
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
            text = "将加入：${preview.ledgerName.displayOr("未命名账本")}",
            style = MaterialTheme.typography.titleSmall,
        )
        Text(
            text = "邀请角色：${ledgerRoleLabel(preview.role)}",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        preview.expiresAt?.takeIf { it.isNotBlank() }?.let {
            Text(
                text = "有效期至：$it",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private fun String?.displayOr(fallback: String): String =
    this?.takeIf { it.isNotBlank() } ?: fallback
