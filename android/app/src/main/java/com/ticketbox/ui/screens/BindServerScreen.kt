package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material3.TextButton
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
import com.ticketbox.ui.components.AppSolidCard
import com.ticketbox.ui.design.AppSpacing

/**
 * BuildConfig-derived server-URL entry rules shared by the unbound auth
 * screens (pairing-code bind and cold-start invitation join). [showInput]
 * follows the long-standing bind-screen rule: advanced builds or a blank
 * packaged default expose the field; gray builds with a packaged default
 * keep it hidden and silently use [defaultUrl].
 */
data class ServerUrlEntryConfig(
    val defaultUrl: String,
    val showInput: Boolean,
)

@Composable
fun BindServerScreen(
    loading: Boolean,
    message: UiText?,
    serverUrlEntry: ServerUrlEntryConfig,
    onBind: (String, String) -> Unit,
    onJoinWithInvitation: () -> Unit,
) {
    var serverUrl by remember(serverUrlEntry.defaultUrl) { mutableStateOf(serverUrlEntry.defaultUrl) }
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
                    if (serverUrlEntry.showInput) {
                        stringResource(R.string.bind_server_hint_with_url)
                    } else {
                        stringResource(R.string.bind_server_hint_no_url)
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (serverUrlEntry.showInput) {
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
                Button(
                    enabled = !loading && serverUrl.isNotBlank() && pairingCode.length == 8,
                    modifier = Modifier.fillMaxWidth(),
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
                TextButton(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = onJoinWithInvitation,
                ) {
                    Text(stringResource(R.string.bind_server_button_join_with_invitation))
                }
            }
        }
        message?.let {
            Spacer(Modifier.height(12.dp))
            Text(it.asString(), color = MaterialTheme.colorScheme.error)
        }
    }
}
