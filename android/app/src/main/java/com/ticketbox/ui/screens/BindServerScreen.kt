package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppSolidCard
import com.ticketbox.ui.design.AppSpacing

@Composable
fun BindServerScreen(
    loading: Boolean,
    message: String?,
    defaultServerUrl: String,
    showServerUrlInput: Boolean,
    onBind: (String, String) -> Unit,
) {
    var serverUrl by remember(defaultServerUrl) { mutableStateOf(defaultServerUrl) }
    var pairingCode by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = AppSpacing.screenHorizontal),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        AuthScreenHeader(
            title = "绑定私人账本",
            subtitle = "完成绑定后，即可在小票夹查看账本。",
        )
        Spacer(Modifier.height(18.dp))
        AppSolidCard(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(AppSpacing.cardPadding),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    if (showServerUrlInput) {
                        "服务拥有者会提供账本地址和绑定码。"
                    } else {
                        "服务拥有者已配置账本地址，请输入绑定码。"
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (showServerUrlInput) {
                    OutlinedTextField(
                        value = serverUrl,
                        onValueChange = { serverUrl = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("账本地址") },
                        placeholder = { Text("向服务拥有者获取") },
                        singleLine = true,
                    )
                }
                OutlinedTextField(
                    value = pairingCode,
                    onValueChange = { pairingCode = it.filter(Char::isDigit).take(6) },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("绑定码") },
                    placeholder = { Text("6 位数字") },
                    singleLine = true,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(
                        enabled = !loading && serverUrl.isNotBlank() && pairingCode.length == 6,
                        modifier = Modifier.weight(1f),
                        onClick = { onBind(serverUrl, pairingCode) },
                    ) {
                        Text(if (loading) "正在绑定" else "绑定账本")
                    }
                    AppOutlinedButton(
                        enabled = false,
                        modifier = Modifier.weight(1f),
                        onClick = {},
                    ) {
                        Text("扫码绑定")
                    }
                }
            }
        }
        message?.let {
            Spacer(Modifier.height(12.dp))
            Text(it, color = MaterialTheme.colorScheme.secondary)
        }
    }
}
