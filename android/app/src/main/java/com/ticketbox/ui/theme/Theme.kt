package com.ticketbox.ui.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin

private val PineScheme = darkColorScheme(
    primary = Color(0xFFD7F7D0),
    onPrimary = Color(0xFF122116),
    secondary = Color(0xFFFFD6A5),
    onSecondary = Color(0xFF2D1A00),
    background = Color(0xFF07120D),
    onBackground = Color(0xFFE9F2EA),
    surface = Color(0xFF132019),
    onSurface = Color(0xFFE8EEE9),
    surfaceVariant = Color(0xFF26362C),
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
    background = Color(0xFF211607),
    onBackground = Color(0xFFF4EBDD),
    surface = Color(0xFF2A2112),
    onSurface = Color(0xFFF0EEE6),
    surfaceVariant = Color(0xFF43351E),
    onSurfaceVariant = Color(0xFFD7D0C4),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
)

private val HarborScheme = darkColorScheme(
    primary = Color(0xFF9BE0D9),
    onPrimary = Color(0xFF062927),
    secondary = Color(0xFFE7B77B),
    onSecondary = Color(0xFF2B1B08),
    tertiary = Color(0xFFC8C6FF),
    onTertiary = Color(0xFF1D214D),
    background = Color(0xFF06141A),
    onBackground = Color(0xFFE7EFF0),
    surface = Color(0xFF10242D),
    onSurface = Color(0xFFE9EEEE),
    surfaceVariant = Color(0xFF1B333B),
    onSurfaceVariant = Color(0xFFC0CFD0),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
)

private val TicketboxShapes = Shapes(
    extraSmall = RoundedCornerShape(10.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(22.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

private val BerryScheme = darkColorScheme(
    primary = Color(0xFFFFB3C8),
    onPrimary = Color(0xFF3D1020),
    secondary = Color(0xFFBCEBD1),
    onSecondary = Color(0xFF092116),
    tertiary = Color(0xFFFFD98D),
    onTertiary = Color(0xFF2D1D00),
    background = Color(0xFF25101B),
    onBackground = Color(0xFFF5E8EF),
    surface = Color(0xFF311B26),
    onSurface = Color(0xFFF1E8EC),
    surfaceVariant = Color(0xFF4A2C3A),
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

fun backgroundBrushForSkin(skin: AppSkin): Brush {
    return when (skin) {
        AppSkin.Pine -> Brush.verticalGradient(
            listOf(
                Color(0xFF06100B),
                Color(0xFF0E1B14),
                Color(0xFF18251D),
            ),
        )
        AppSkin.Pomelo -> Brush.verticalGradient(
            listOf(
                Color(0xFF281706),
                Color(0xFF1D2112),
                Color(0xFF10241D),
            ),
        )
        AppSkin.Harbor -> Brush.verticalGradient(
            listOf(
                Color(0xFF041017),
                Color(0xFF0A1D25),
                Color(0xFF112D32),
                Color(0xFF1D2421),
            ),
        )
        AppSkin.Berry -> Brush.verticalGradient(
            listOf(
                Color(0xFF2B1020),
                Color(0xFF211B33),
                Color(0xFF10261B),
            ),
        )
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
        shapes = TicketboxShapes,
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(backgroundBrushForSkin(skin)),
        ) {
            CompositionLocalProvider(LocalContentColor provides MaterialTheme.colorScheme.onBackground) {
                content()
            }
        }
    }
}
