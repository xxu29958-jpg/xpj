package com.ticketbox.ui.screens.settings

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R

@Composable
fun AboutScreen(
    appVersionName: String,
    appVersionCode: Int,
    onBack: () -> Unit,
    onOpenSecurity: () -> Unit,
) {
    var helpOpen by rememberSaveable { mutableStateOf(false) }
    SettingsPageFrame(
        title = stringResource(R.string.settings_about_page_title),
        subtitle = stringResource(R.string.settings_about_page_subtitle),
        onBack = onBack,
    ) {
        SettingsEntryRow(stringResource(R.string.settings_about_build_title),
            stringResource(R.string.settings_about_version, appVersionName, appVersionCode),
            R.drawable.ic_lucide_info, onClick = null)
        SettingsEntryRow(stringResource(R.string.settings_about_security_title),
            stringResource(R.string.settings_about_security_body), R.drawable.ic_lucide_shield_check, onClick = onOpenSecurity)
        SettingsEntryRow(stringResource(R.string.settings_about_help_title),
            stringResource(R.string.settings_about_help_body), R.drawable.ic_lucide_book_open, onClick = { helpOpen = !helpOpen },
            options = SettingsEntryRowOptions(expanded = helpOpen))
        if (helpOpen) {
            AboutHelpText(R.string.settings_about_confirm_title, R.string.settings_about_confirm_body)
            AboutHelpText(R.string.settings_about_authority_title, R.string.settings_about_authority_body)
            AboutHelpText(R.string.settings_about_privacy_title, R.string.settings_about_privacy_body)
        }
        SettingsEntryRow(stringResource(R.string.settings_about_owner_title),
            stringResource(R.string.settings_about_owner_body), R.drawable.ic_lucide_info, onClick = null)
    }
}

@Composable
private fun AboutHelpText(title: Int, body: Int) {
    Text(stringResource(title), style = MaterialTheme.typography.titleSmall)
    Text(stringResource(body), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
}
