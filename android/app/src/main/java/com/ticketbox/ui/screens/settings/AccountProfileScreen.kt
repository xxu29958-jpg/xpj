package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import com.ticketbox.ui.components.AppPrimaryButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.AccountProfileUiState

@Composable
fun AccountProfileScreen(
    state: AccountProfileUiState,
    onNameChange: (String) -> Unit,
    onSave: () -> Unit,
    onRefresh: () -> Unit,
    onBack: () -> Unit,
) {
    SettingsPageFrame(
        title = stringResource(R.string.account_profile_title),
        subtitle = stringResource(R.string.account_profile_subtitle),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = state.tone) },
    ) {
        SettingsOpenPanel {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                state.profile?.let { Text(stringResource(R.string.account_profile_current, it.displayName)) }
                OutlinedTextField(
                    value = state.name,
                    onValueChange = onNameChange,
                    label = { Text(stringResource(R.string.account_profile_name)) },
                    enabled = !state.busy,
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                AppPrimaryButton(
                    text = stringResource(if (state.busy) R.string.account_profile_working else R.string.account_profile_save),
                    onClick = onSave, enabled = state.fresh && !state.busy && state.name.isNotBlank(),
                    modifier = Modifier.fillMaxWidth())
                TextButton(onClick = onRefresh, enabled = !state.busy) {
                    Text(stringResource(R.string.account_profile_refresh))
                }
                Text(stringResource(R.string.account_profile_online))
            }
        }
    }
}
