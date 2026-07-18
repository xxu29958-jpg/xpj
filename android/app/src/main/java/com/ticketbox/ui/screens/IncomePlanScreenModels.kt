package com.ticketbox.ui.screens

import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.IncomePlanLoadState
import com.ticketbox.viewmodel.IncomePlanUiState

internal enum class IncomePlanBodyState {
    Loading,
    LoadFailed,
    Empty,
    Content,
}

internal fun incomePlanBodyState(
    loadState: IncomePlanLoadState,
    activeCount: Int,
    archivedCount: Int,
): IncomePlanBodyState {
    val hasReadableRows = activeCount > 0 || archivedCount > 0
    return when {
        hasReadableRows -> IncomePlanBodyState.Content
        loadState == IncomePlanLoadState.Failed -> IncomePlanBodyState.LoadFailed
        loadState == IncomePlanLoadState.Loaded -> IncomePlanBodyState.Empty
        else -> IncomePlanBodyState.Loading
    }
}

internal fun incomePlanInlineMessage(
    bodyState: IncomePlanBodyState,
    message: UiText?,
): UiText? = message?.takeIf {
    bodyState == IncomePlanBodyState.Content || bodyState == IncomePlanBodyState.Empty
}

internal fun incomePlanShowsSummary(bodyState: IncomePlanBodyState): Boolean =
    bodyState == IncomePlanBodyState.Content || bodyState == IncomePlanBodyState.Empty

internal fun incomePlanSubmitEnabled(state: IncomePlanUiState): Boolean =
    !state.isSubmitting && state.addDraft.isValid
