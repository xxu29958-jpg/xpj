package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.components.AppLoadingState
import com.ticketbox.ui.components.AppPageChrome
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppScrollablePageChrome
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.PageRole
import com.ticketbox.viewmodel.SessionVerificationState

@Composable
internal fun SessionVerificationGate(
    backgroundSettings: BackgroundSettings,
    currentSkin: AppSkin,
    verification: SessionVerificationState,
    message: UiText?,
    onRetry: () -> Unit,
) {
    ImmersiveBackgroundScaffold(
        backgroundSettings = backgroundSettings,
        currentSkin = currentSkin,
        surfaceRole = SurfaceRole.Auth,
    ) {
        AppPageScrollableColumn(
            chrome = AppScrollablePageChrome(
                page = AppPageChrome(
                    role = PageRole.Auth,
                    hasBottomBar = false,
                ),
            ),
        ) {
            AppPageHeader(
                title = stringResource(R.string.app_session_verification_title),
                subtitle = stringResource(R.string.app_session_identity_pending),
            )
            if (verification == SessionVerificationState.Verifying) {
                AppLoadingState(
                    title = stringResource(R.string.app_session_verification_loading),
                    body = stringResource(R.string.app_session_verification_loading_body),
                )
            } else {
                AppStatusBanner(
                    message = message ?: UiText.res(R.string.app_session_identity_pending),
                    tone = MessageTone.Danger,
                )
                AppPrimaryButton(
                    text = stringResource(R.string.app_session_verification_retry),
                    icon = Icons.Default.Refresh,
                    modifier = Modifier.fillMaxWidth(),
                    onClick = onRetry,
                )
            }
        }
    }
}
