package com.ticketbox.ui.appearance

import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource

object AppearanceDefaults {
    fun backgroundSourceLabel(settings: BackgroundSettings): String {
        return when (settings.source) {
            BackgroundSource.ThemeDefault -> "跟随主题"
            BackgroundSource.BuiltIn -> BackgroundCatalog.find(settings.builtInBackgroundId)?.name ?: "内置背景"
            BackgroundSource.CustomImage -> "自定义图片"
        }
    }
}
