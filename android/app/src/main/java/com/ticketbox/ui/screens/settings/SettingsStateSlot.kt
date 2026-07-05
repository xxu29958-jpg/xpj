package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppContentStateCopy
import com.ticketbox.ui.components.AppContentStatePresentation
import com.ticketbox.ui.components.AppContentStateSpec
import com.ticketbox.ui.components.AppContentStateSlot

internal data class SettingsStateSlotCopy(
    val loadingTitle: String,
    val loadingBody: String,
    val emptyText: String,
    val emptyTitle: String? = null,
    val emptyBody: String? = null,
)

internal data class SettingsStateSlotMessage(
    val text: UiText,
    val tone: MessageTone = MessageTone.Neutral,
)

@Composable
internal fun SettingsListStateSlot(
    loading: Boolean,
    hasData: Boolean,
    copy: SettingsStateSlotCopy,
    modifier: Modifier = Modifier,
    message: SettingsStateSlotMessage? = null,
) {
    AppContentStateSlot(
        state = AppContentStateSpec(
            loading = loading,
            hasData = hasData,
            copy = AppContentStateCopy(
                loadingTitle = copy.loadingTitle,
                loadingBody = copy.loadingBody,
                emptyText = copy.emptyText,
                emptyTitle = copy.emptyTitle,
                emptyBody = copy.emptyBody,
            ),
            message = message?.text,
            messageTone = message?.tone ?: MessageTone.Neutral,
            presentation = AppContentStatePresentation.Inline,
        ),
        modifier = modifier,
    )
}
