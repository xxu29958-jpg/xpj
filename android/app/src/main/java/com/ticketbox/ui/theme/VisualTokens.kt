package com.ticketbox.ui.theme

import com.ticketbox.domain.model.AppSkin

typealias ThemeVisuals = com.ticketbox.ui.design.ThemeVisuals

val LocalThemeVisuals = com.ticketbox.ui.design.LocalThemeVisuals

fun themeVisualsForSkin(skin: AppSkin): ThemeVisuals {
    return com.ticketbox.ui.design.themeVisualsForSkin(skin)
}
