package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.AppThemeMode

@StringRes
internal fun appThemeModeNameRes(mode: AppThemeMode): Int = when (mode) {
    AppThemeMode.Paper -> R.string.appearance_skin_name_paper
    AppThemeMode.Midnight -> R.string.appearance_skin_name_midnight
    AppThemeMode.System -> R.string.appearance_theme_mode_name_system
}

@StringRes
internal fun appThemeModeDescriptionRes(mode: AppThemeMode): Int = when (mode) {
    AppThemeMode.Paper -> R.string.appearance_skin_description_paper
    AppThemeMode.Midnight -> R.string.appearance_skin_description_midnight
    AppThemeMode.System -> R.string.appearance_theme_mode_description_system
}
