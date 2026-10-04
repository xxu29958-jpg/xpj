package com.ticketbox.ui.design

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.graphics.luminance
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable

/** Light surfaces for settings destinations and the first binding introduction. */
object SettingsColors {
    val householdEntry = Color(0xFFF8E7D6)
    val appearanceEntry = Color(0xFFEEE8F7)
    val connectionEntry = Color(0xFFF1EDDA)
    val generalEntry = Color(0xFFE5EED7)
    val bindingIntroduction = Color(0xFFEAF0D6)
    val sessionCredential = appearanceEntry
    val offlineCopy = householdEntry
    val sessionExit = connectionEntry
}

@Composable
fun settingsEntrySurface(tint: Color): Color {
    val surface = MaterialTheme.colorScheme.surface
    return if (surface.luminance() < 0.5f) lerp(surface, tint, 0.12f) else tint
}

@Composable
fun settingsEntrySurface(tint: Color): Color {
    val surface = MaterialTheme.colorScheme.surface
    return if (surface.luminance() < 0.5f) lerp(surface, tint, 0.12f) else tint
}
