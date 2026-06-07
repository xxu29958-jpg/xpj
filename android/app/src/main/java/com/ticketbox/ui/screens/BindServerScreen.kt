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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppSolidCard
import com.ticketbox.ui.design.AppSpacing

@Composable
fun BindServerScreen(
    loading: Boolean,
    message: UiText?,
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
            title = stringResource(R.string.bind_server_header_title),
            subtitle = stringResource(R.string.bind_server_header_subtitle),
        )
        Spacer(Modifier.height(18.dp))
        AppSolidCard(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(AppSpacing.cardPadding),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    if (showServerUrlInput) {
                        stringResource(R.string.bind_server_hint_with_url)
                    } else {
                        stringResource(R.string.bind_server_hint_no_url)
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (showServerUrlInput) {
                    OutlinedTextField(
                        value = serverUrl,
                        onValueChange = { serverUrl = it },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text(stringResource(R.string.bind_server_field_url_label)) },
                        placeholder = { Text(stringResource(R.string.bind_server_field_url_placeholder)) },
                        singleLine = true,
                    )
                }
                OutlinedTextField(
                    value = pairingCode,
                    onValueChange = { pairingCode = it.filter(Char::isDigit).take(8) },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.bind_server_field_code_label)) },
                    placeholder = { Text(stringResource(R.string.bind_server_field_code_placeholder)) },
                    singleLine = true,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(
                        enabled = !loading && serverUrl.isNotBlank() && pairingCode.length == 8,
                        modifier = Modifier.weight(1f),
                        onClick = { onBind(serverUrl, pairingCode) },
                    ) {
                        Text(
                            if (loading) {
                                stringResource(R.string.bind_server_button_binding)
                            } else {
                                stringResource(R.string.bind_server_button_bind)
                            },
                        )
                    }
                    AppOutlinedButton(
                        enabled = false,
                        modifier = Modifier.weight(1f),
                        onClick = {},
                    ) {
                        Text(stringResource(R.string.bind_server_button_scan))
                    }
                }
            }
        }
        message?.let {
            Spacer(Modifier.height(12.dp))
            Text(it.asString(), color = MaterialTheme.colorScheme.secondary)
        }
    }
}
