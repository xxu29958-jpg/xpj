package com.ticketbox.ui.appearance

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.BackgroundSource

object AppearanceDefaults {
    @StringRes
    fun backgroundSourceFallbackLabelRes(source: BackgroundSource): Int = when (source) {
        BackgroundSource.ThemeDefault -> R.string.appearance_background_source_theme_default
        BackgroundSource.BuiltIn -> R.string.appearance_background_source_builtin
        BackgroundSource.CustomImage -> R.string.appearance_background_source_custom_image
    }
}
