package com.ticketbox.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val DarkScheme = darkColorScheme(
    primary = Color(0xFFD7F7D0),
    onPrimary = Color(0xFF122116),
    secondary = Color(0xFFFFD6A5),
    onSecondary = Color(0xFF2D1A00),
    background = Color(0xFF101417),
    onBackground = Color(0xFFE8EEE9),
    surface = Color(0xFF171D20),
    onSurface = Color(0xFFE8EEE9),
    surfaceVariant = Color(0xFF243035),
    onSurfaceVariant = Color(0xFFC5D0CA),
)

@Composable
fun TicketboxTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkScheme,
        typography = MaterialTheme.typography,
        content = content,
    )
}
