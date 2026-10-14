package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import com.ticketbox.ui.components.AppPrimaryButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
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
    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Settings,
            title = stringResource(R.string.account_profile_title),
            subtitle = stringResource(R.string.account_profile_subtitle),
            backText = stringResource(R.string.settings_page_back_to_settings),
            onBack = onBack,
        ),
        slots = AppSecondaryPageSlots(
            status = { AppStatusBanner(message = state.message, tone = state.tone) },
            bottomBar = {
                AppFloatingActionBar {
                    AppPrimaryButton(
                        text = stringResource(if (state.busy) R.string.account_profile_working else R.string.account_profile_save),
                        onClick = onSave, enabled = state.fresh && !state.busy && state.name.isNotBlank(),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
        ),
    ) {
        SettingsOpenPanel {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                state.profile?.let { Text(stringResource(R.string.account_profile_current, it.displayName)) }
                AppTextInput(
                    state = AppTextInputState(value = state.name, label = stringResource(R.string.account_profile_name),
                        enabled = !state.busy),
                    actions = AppTextInputActions(onValueChange = onNameChange),
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    text = stringResource(R.string.account_profile_online),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                TextButton(onClick = onRefresh, enabled = !state.busy) {
                    Text(stringResource(R.string.account_profile_refresh))
                }
            }
        }
    }
}
