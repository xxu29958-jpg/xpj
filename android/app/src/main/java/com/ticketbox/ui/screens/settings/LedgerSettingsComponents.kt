package com.ticketbox.ui.screens.settings

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppPageChrome
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.AppScrollablePageChrome
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppSpacing

internal data class SettingsPageAction(val label: String, val enabled: Boolean, val onClick: () -> Unit)

/** The ledger directory and invitation form share the selected fixed-action layout. */
@Composable
internal fun LedgerSettingsPage(
    header: ManagementPageHeader,
    onBack: () -> Unit,
    action: SettingsPageAction,
    content: @Composable () -> Unit,
) {
    BackHandler(onBack = onBack)
    AppPageScrollableColumn(
        chrome = AppScrollablePageChrome(
            page = AppPageChrome(role = AppPageRole.Settings, hasBottomBar = false),
            contentWidth = AppAdaptiveContentWidth.Secondary,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ),
        bottomBar = {
            Surface(color = MaterialTheme.colorScheme.background) {
                SettingsPrimaryAction(action.label, enabled = action.enabled, onClick = action.onClick,
                    modifier = Modifier.fillMaxWidth().navigationBarsPadding()
                        .padding(horizontal = AppSpacing.screenHorizontal, vertical = AppSpacing.contentGap))
            }
        },
    ) {
        SettingsPageHeading(header.title, header.subtitle, onBack,
            backLabel = header.chrome.backText ?: stringResource(R.string.settings_root_page_title))
        content()
    }
}
