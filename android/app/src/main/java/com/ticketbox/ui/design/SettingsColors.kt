package com.ticketbox.ui.design

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Settings roles consume the same resolved light/dark surfaces as the rest of the product. */
object SettingsColors {
    val householdEntry: Color @Composable get() = LocalThemeVisuals.current.surfaceApricot
    val appearanceEntry: Color @Composable get() = LocalThemeVisuals.current.surfaceLilac
    val connectionEntry: Color @Composable get() = LocalThemeVisuals.current.surfaceSand
    val generalEntry: Color @Composable get() = LocalThemeVisuals.current.brandPrimaryBg
    val bindingIntroduction: Color @Composable get() = LocalThemeVisuals.current.brandPrimaryBg
    val sessionCredential: Color @Composable get() = appearanceEntry
    val offlineCopy: Color @Composable get() = householdEntry
    val sessionExit: Color @Composable get() = connectionEntry
}
