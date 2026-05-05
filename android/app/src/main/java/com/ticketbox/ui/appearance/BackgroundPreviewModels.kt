package com.ticketbox.ui.appearance

import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode

enum class PreviewPage(
    val displayName: String,
) {
    Pending("待确认"),
    Ledger("账本"),
    Stats("统计"),
    Edit("编辑确认"),
}

data class BackgroundPreviewState(
    val previewSettings: BackgroundSettings,
    val appliedSettings: BackgroundSettings,
    val selectedPreviewPage: PreviewPage = PreviewPage.Pending,
) {
    fun withImmersionMode(mode: ImmersionMode): BackgroundPreviewState {
        return copy(previewSettings = previewSettings.copy(immersionMode = mode))
    }

    fun isDirty(): Boolean = previewSettings != appliedSettings
}
