package com.ticketbox.ui.screens.settings

import android.graphics.BitmapFactory
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.ui.appearance.AppearanceDefaults
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.appearance.BuiltInBackground
import com.ticketbox.ui.appearance.BuiltInBackgroundCategory
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.appearance.background.TicketboxBackgroundLayer
import com.ticketbox.ui.appearance.background.resolveCardContainerAlpha
import com.ticketbox.ui.appearance.background.resolveGlobalScrim
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.ScreenHeader
import com.ticketbox.ui.components.SoftPanel
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.theme.backgroundBrushForSkin
import com.ticketbox.ui.theme.colorSchemeForSkin
import com.ticketbox.viewmodel.SettingsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun DataExportScreen(
    state: SettingsUiState,
    onBack: () -> Unit,
    onSync: () -> Unit,
    onClearCache: () -> Unit,
    onSaveMonthlyBudget: (Long?) -> Unit,
) {
    var budgetInput by remember(state.monthlyBudgetCents) {
        mutableStateOf(formatAmountInput(state.monthlyBudgetCents))
    }
    var localMessage by remember { mutableStateOf<String?>(null) }
    var showClearCacheDialog by remember { mutableStateOf(false) }

    if (showClearCacheDialog) {
        AlertDialog(
            onDismissRequest = { showClearCacheDialog = false },
            title = { Text("清除手机本地数据？") },
            text = { Text("清除后，手机里已缓存的账单会移除。服务端账单不会删除，之后可以重新同步。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        showClearCacheDialog = false
                        onClearCache()
                    },
                ) {
                    Text("确定清除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { showClearCacheDialog = false }) {
                    Text("取消")
                }
            },
        )
    }

    SettingsPageFrame(
        title = "数据与导出",
        subtitle = "本地缓存只保存在手机，CSV 导出在账本页发起。",
        onBack = onBack,
    ) {
        SettingsSection(title = "月度预算", icon = Icons.Filled.FileDownload) {
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        text = state.monthlyBudgetCents?.let { "当前预算 ${formatAmount(it)}" } ?: "未设置预算",
                        style = MaterialTheme.typography.titleSmall,
                    )
                    OutlinedTextField(
                        value = budgetInput,
                        onValueChange = { budgetInput = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("预算，单位元") },
                        placeholder = { Text("3000") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Button(
                            modifier = Modifier.weight(1f),
                            onClick = {
                                val amount = parseAmountCents(budgetInput)
                                if (budgetInput.isNotBlank() && (amount == null || amount <= 0L)) {
                                    localMessage = "请输入大于 0 的预算金额。"
                                    return@Button
                                }
                                localMessage = null
                                onSaveMonthlyBudget(amount)
                            },
                        ) {
                            Text("保存预算")
                        }
                        OutlinedButton(
                            modifier = Modifier.weight(1f),
                            enabled = state.monthlyBudgetCents != null || budgetInput.isNotBlank(),
                            onClick = {
                                budgetInput = ""
                                localMessage = null
                                onSaveMonthlyBudget(null)
                            },
                        ) {
                            Text("关闭预算")
                        }
                    }
                }
            }
        }
        SettingsSection(title = "同步与缓存", icon = Icons.Filled.RestartAlt) {
            Text(
                text = "已确认账单会缓存在手机，离线时账本页仍可查看本地记录。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(
                    modifier = Modifier.weight(1f),
                    enabled = !state.busy,
                    onClick = onSync,
                ) {
                    Text(if (state.busy) "同步中" else "重新同步")
                }
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    onClick = { showClearCacheDialog = true },
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Text("清除缓存")
                }
            }
            Text(
                text = "CSV 导出请在账本页选择月份和分类后点击导出账单；没有账单时按钮会禁用。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        state.message?.let { Text(it, color = MaterialTheme.colorScheme.secondary) }
        localMessage?.let { Text(it, color = MaterialTheme.colorScheme.secondary) }
    }
}

