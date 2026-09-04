package com.ticketbox.viewmodel

import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText

data class AppearanceUiState(
    val backgroundSettings: BackgroundSettings = BackgroundSettings(),
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val editor: BackgroundEditorState? = null,
    val importing: Boolean = false,
)

data class BackgroundEditorState(
    val settings: BackgroundSettings,
    val saving: Boolean = false,
    val message: UiText? = null,
)
