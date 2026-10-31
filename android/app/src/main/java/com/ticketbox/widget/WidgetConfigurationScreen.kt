package com.ticketbox.widget

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.security.LocalSessionVersion
import com.ticketbox.ui.theme.TicketboxTheme

internal data class WidgetConfigurationState(
    val version: LocalSessionVersion? = null,
    val ledgerName: String? = null,
    val showSummary: Boolean = false,
    val error: String? = null,
)

@Composable
internal fun WidgetConfigurationScreen(
    state: WidgetConfigurationState,
    onSave: (Boolean) -> Unit,
    onOpenApp: () -> Unit,
    onCancel: () -> Unit,
) {
    var showSummary by rememberSaveable(state.version, state.showSummary) { mutableStateOf(state.showSummary) }
    TicketboxTheme(skin = if (isSystemInDarkTheme()) AppSkin.Midnight else AppSkin.Paper) {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(Modifier.safeDrawingPadding().verticalScroll(rememberScrollState()).padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(20.dp)) {
                Text(stringResource(R.string.widget_configure_title), style = MaterialTheme.typography.headlineMedium)
                Text(stringResource(R.string.widget_configure_description))
                Text(state.ledgerName ?: stringResource(R.string.widget_bind_first), style = MaterialTheme.typography.titleMedium)
                Row(modifier = Modifier.fillMaxWidth().toggleable(value = showSummary, enabled = state.version != null,
                    role = Role.Checkbox, onValueChange = { showSummary = it }), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = showSummary, enabled = state.version != null, onCheckedChange = null)
                    Text(stringResource(R.string.widget_show_summary))
                }
                Text(stringResource(R.string.widget_privacy_notice), style = MaterialTheme.typography.bodyMedium)
                state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Button(onClick = { onSave(showSummary) }, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.widget_save))
                }
                TextButton(onClick = onOpenApp) { Text(stringResource(R.string.widget_open_app)) }
                TextButton(onClick = onCancel) { Text(stringResource(R.string.widget_cancel)) }
            }
        }
    }
}
