package com.ticketbox.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

private val PineScheme = darkColorScheme(
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
    tertiary = Color(0xFFFFB4C8),
    onTertiary = Color(0xFF3B1020),
)

private val PomeloScheme = darkColorScheme(
    primary = Color(0xFFFFD276),
    onPrimary = Color(0xFF2A1C00),
    secondary = Color(0xFFA9EBCB),
    onSecondary = Color(0xFF062116),
    tertiary = Color(0xFFFFA6B8),
    onTertiary = Color(0xFF3A101B),
    background = Color(0xFF141411),
    onBackground = Color(0xFFF0EEE6),
    surface = Color(0xFF1D1C18),
    onSurface = Color(0xFFF0EEE6),
    surfaceVariant = Color(0xFF302C24),
    onSurfaceVariant = Color(0xFFD7D0C4),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
)

private val HarborScheme = darkColorScheme(
    primary = Color(0xFF9BE7DE),
    onPrimary = Color(0xFF003733),
    secondary = Color(0xFFFFD8A8),
    onSecondary = Color(0xFF2B1B00),
    tertiary = Color(0xFFC9D7FF),
    onTertiary = Color(0xFF17254A),
    background = Color(0xFF101414),
    onBackground = Color(0xFFE9EEEE),
    surface = Color(0xFF171D1D),
    onSurface = Color(0xFFE9EEEE),
    surfaceVariant = Color(0xFF243030),
    onSurfaceVariant = Color(0xFFC7D1CF),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
)

private val BerryScheme = darkColorScheme(
    primary = Color(0xFFFFB3C8),
    onPrimary = Color(0xFF3D1020),
    secondary = Color(0xFFBCEBD1),
    onSecondary = Color(0xFF092116),
    tertiary = Color(0xFFFFD98D),
    onTertiary = Color(0xFF2D1D00),
    background = Color(0xFF171215),
    onBackground = Color(0xFFF1E8EC),
    surface = Color(0xFF21191E),
    onSurface = Color(0xFFF1E8EC),
    surfaceVariant = Color(0xFF34262D),
    onSurfaceVariant = Color(0xFFD8C6CE),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
)

fun colorSchemeForSkin(skin: AppSkin): ColorScheme {
    return when (skin) {
        AppSkin.Pine -> PineScheme
        AppSkin.Pomelo -> PomeloScheme
        AppSkin.Harbor -> HarborScheme
        AppSkin.Berry -> BerryScheme
    }
}

@Composable
fun TicketboxTheme(
    skin: AppSkin,
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = colorSchemeForSkin(skin),
        typography = MaterialTheme.typography,
        content = content,
    )
}
