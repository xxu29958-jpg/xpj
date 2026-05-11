package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FolderShared
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.ui.components.SoftPanel
import kotlinx.coroutines.launch

private const val LEDGER_NAME_MAX = 60

/**
 * v0.4-alpha1 minimum-viable ledger management surface.
 *
 * Renders the list of ledgers the current account belongs to, lets the user
 * switch between them (rotating the session token server-side) and create a
 * new ledger. Ownership is decided server-side; this screen never trusts
 * client-supplied roles for authorization.
 */
@Composable
fun LedgerSwitcherScreen(
    repository: LedgerRepository,
    activeLedgerId: String?,
    onBack: () -> Unit,
    onSwitched: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var ledgers by remember { mutableStateOf<List<LedgerSummary>>(repository.cachedLedgers()) }
    var loading by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    var newLedgerName by remember { mutableStateOf("") }

    suspend fun refresh() {
        loading = true
        message = null
        repository.refreshLedgers()
            .onSuccess { ledgers = it }
            .onFailure { message = it.message ?: "获取账本失败。" }
        loading = false
    }

    LaunchedEffect(Unit) {
        refresh()
    }

    SettingsPageFrame(
        title = "账本",
        subtitle = "v0.4-alpha1：实验中，可在多个账本之间切换。",
        onBack = onBack,
    ) {
        SettingsSection(title = "已加入的账本", icon = Icons.Filled.FolderShared) {
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    if (ledgers.isEmpty() && !loading) {
                        Text(
                            text = "还没有可显示的账本。请稍后下拉刷新。",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    ledgers.forEach { ledger ->
                        val isActive = ledger.ledgerId == activeLedgerId
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                        ) {
                            Column {
                                Text(
                                    text = if (ledger.isDefault) ledger.name + "（默认）" else ledger.name,
                                    style = MaterialTheme.typography.titleSmall,
                                )
                                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                                    LedgerRoleChip(role = ledger.role)
                                    if (isActive) {
                                        Spacer(Modifier.width(6.dp))
                                        Text(
                                            text = "当前",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                            }
                            if (!isActive) {
                                TextButton(onClick = {
                                    if (loading) return@TextButton
                                    scope.launch {
                                        loading = true
                                        message = null
                                        repository.switchLedger(ledger.ledgerId)
                                            .onSuccess {
                                                message = "已切换到“${it.name}”"
                                                onSwitched()
                                                refresh()
                                            }
                                            .onFailure {
                                                message = it.message ?: "切换账本失败。"
                                            }
                                        loading = false
                                    }
                                }) { Text("切换") }
                            }
                        }
                    }
                    OutlinedButton(
                        onClick = { scope.launch { refresh() } },
                        enabled = !loading,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text(if (loading) "刷新中…" else "刷新列表") }
                }
            }
        }

        SettingsSection(title = "新建账本", icon = Icons.Filled.FolderShared) {
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = "账本名称最多 $LEDGER_NAME_MAX 个字。新建后不会自动切换，可以在上方点击“切换”。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    OutlinedTextField(
                        value = newLedgerName,
                        onValueChange = { value ->
                            // Trim hard upper bound on input to prevent oversize requests.
                            newLedgerName = value.take(LEDGER_NAME_MAX)
                        },
                        label = { Text("账本名称") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Button(
                        onClick = {
                            val name = newLedgerName.trim()
                            if (name.isEmpty()) {
                                message = "请填写账本名称。"
                                return@Button
                            }
                            scope.launch {
                                loading = true
                                message = null
                                repository.createLedger(name)
                                    .onSuccess {
                                        message = "已新建账本“${it.name}”"
                                        newLedgerName = ""
                                        refresh()
                                    }
                                    .onFailure {
                                        message = it.message ?: "新建账本失败。"
                                    }
                                loading = false
                            }
                        },
                        enabled = !loading,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("新建账本") }
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

/**
 * v0.4-beta1 role chip. Mirrors the colour palette used by the /web role
 * badge: owner→amber, member→blue, viewer→grey. Unknown roles fall back to
 * the surface-variant tone so the UI never drops information silently.
 */
@Composable
private fun LedgerRoleChip(role: String) {
    val (label, container, content) = when (role) {
        "owner" -> Triple("所有者", Color(0xFFFFE2A0), Color(0xFF5A3B00))
        "member" -> Triple("成员（可写）", Color(0xFFC9DCFF), Color(0xFF1F3D7A))
        "viewer" -> Triple("只读", Color(0xFFE2E2E6), Color(0xFF40404A))
        else -> Triple(role, Color(0xFFE2E2E6), Color(0xFF40404A))
    }
    androidx.compose.foundation.layout.Box(
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
