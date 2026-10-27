package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.NotificationCaptureFailure
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun NotificationCaptureFailureStatus(
    failure: NotificationCaptureFailure?,
    onAcknowledged: (NotificationCaptureFailure) -> Unit,
) {
    if (failure == null) return
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        AppStatusBanner(UiText.res(R.string.notification_capture_not_saved), MessageTone.Danger)
        if (failure.persistenceFailed) {
            AppStatusBanner(UiText.res(R.string.notification_capture_status_not_saved), MessageTone.Danger)
        }
        AppSecondaryButton(
            text = stringResource(R.string.notification_capture_acknowledge),
            onClick = { onAcknowledged(failure) },
        )
    }
}
