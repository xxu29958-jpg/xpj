package com.ticketbox.ui.theme

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.graphics.Color as AndroidColor
import androidx.compose.foundation.background
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.Alignment
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import android.view.View
import androidx.core.view.WindowInsetsControllerCompat
import com.ticketbox.domain.model.AppSkin

private val PineScheme = lightColorScheme(
    primary = Color(0xFF0E5C4F),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFDCECE5),
    onPrimaryContainer = Color(0xFF103D35),
    secondary = Color(0xFFB1814A),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFEFE1CF),
    onSecondaryContainer = Color(0xFF4B3118),
    tertiary = Color(0xFF2D7A80),
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFDDEDEF),
    onTertiaryContainer = Color(0xFF143E42),
    background = Color(0xFFF1F6F1),
    onBackground = Color(0xFF192322),
    surface = Color(0xFFFFFCF7),
    onSurface = Color(0xFF1D2524),
    surfaceVariant = Color(0xFFE4EEE8),
    onSurfaceVariant = Color(0xFF76817E),
    outline = Color(0xFFD8DCD5),
    outlineVariant = Color(0xFFE4E7DF),
    error = Color(0xFF8B3B34),
    onError = Color(0xFFFFFFFF),
)

private val PomeloScheme = lightColorScheme(
    primary = Color(0xFFE6981B),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFFFE4B6),
    onPrimaryContainer = Color(0xFF5C3500),
    secondary = Color(0xFF8A6A2D),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFF2E4C6),
    onSecondaryContainer = Color(0xFF473513),
    tertiary = Color(0xFF2D7A80),
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFDDEEEF),
    onTertiaryContainer = Color(0xFF143E42),
    background = Color(0xFFFFF6E6),
    onBackground = Color(0xFF221F19),
    surface = Color(0xFFFFFCF7),
    onSurface = Color(0xFF25221C),
    surfaceVariant = Color(0xFFF6E8D1),
    onSurfaceVariant = Color(0xFF81786D),
    outline = Color(0xFFE0D8CA),
    outlineVariant = Color(0xFFECE4D8),
    error = Color(0xFF8B3B34),
    onError = Color(0xFFFFFFFF),
)

private val HarborScheme = lightColorScheme(
    primary = Color(0xFF245D78),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFDDEAF0),
    onPrimaryContainer = Color(0xFF123648),
    secondary = Color(0xFF185B4F),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFE0ECE8),
    onSecondaryContainer = Color(0xFF123B35),
    tertiary = Color(0xFFD59A4C),
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFF2E3CC),
    onTertiaryContainer = Color(0xFF55360E),
    background = Color(0xFFF2F6F7),
    onBackground = Color(0xFF192322),
    surface = Color(0xFFFFFCF7),
    onSurface = Color(0xFF1E2524),
    surfaceVariant = Color(0xFFE3ECEE),
    onSurfaceVariant = Color(0xFF6C7D82),
    outline = Color(0xFFD8DDD6),
    outlineVariant = Color(0xFFE4E8E1),
    error = Color(0xFF8B3B34),
    onError = Color(0xFFFFFFFF),
)

private val TicketboxShapes = Shapes(
    extraSmall = RoundedCornerShape(12.dp),
    small = RoundedCornerShape(16.dp),
    medium = RoundedCornerShape(22.dp),
    large = RoundedCornerShape(28.dp),
    extraLarge = RoundedCornerShape(34.dp),
)

private val BerryScheme = lightColorScheme(
    primary = Color(0xFFA83C5A),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFF2D7DF),
    onPrimaryContainer = Color(0xFF511B2A),
    secondary = Color(0xFFC96C86),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFF5DCE3),
    onSecondaryContainer = Color(0xFF5E2637),
    tertiary = Color(0xFF8B7A65),
    onTertiary = Color(0xFFFFFFFF),
    background = Color(0xFFF6EFF2),
    onBackground = Color(0xFF241D20),
    surface = Color(0xFFFFFAFC),
    onSurface = Color(0xFF251F22),
    surfaceVariant = Color(0xFFF0E4E9),
    onSurfaceVariant = Color(0xFF83747B),
    outline = Color(0xFFE0D4DA),
    outlineVariant = Color(0xFFEDE1E7),
    error = Color(0xFF8B3B34),
    onError = Color(0xFFFFFFFF),
)

private val NightScheme = darkColorScheme(
    primary = Color(0xFF2BB49A),
    onPrimary = Color(0xFF062621),
    primaryContainer = Color(0xFF0A4139),
    onPrimaryContainer = Color(0xFFC7F2E8),
    secondary = Color(0xFF84A7B7),
    onSecondary = Color(0xFF102A35),
    secondaryContainer = Color(0xFF173744),
    onSecondaryContainer = Color(0xFFD4E8EF),
    tertiary = Color(0xFFD2A46E),
    onTertiary = Color(0xFF3A260D),
    tertiaryContainer = Color(0xFF4D3617),
    onTertiaryContainer = Color(0xFFF7E1C1),
    background = Color(0xFF07151A),
    onBackground = Color(0xFFE7F1EF),
    surface = Color(0xFF0D2027),
    onSurface = Color(0xFFEAF2F0),
    surfaceVariant = Color(0xFF183039),
    onSurfaceVariant = Color(0xFFB6C6C8),
    outline = Color(0xFF31515A),
    outlineVariant = Color(0xFF1C3B43),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
)

fun colorSchemeForSkin(skin: AppSkin): ColorScheme {
    return when (skin) {
        AppSkin.Pine -> PineScheme
        AppSkin.Pomelo -> PomeloScheme
        AppSkin.Harbor -> HarborScheme
        AppSkin.Berry -> BerryScheme
        AppSkin.Night -> NightScheme
    }
}

fun backgroundBrushForSkin(skin: AppSkin): Brush {
    val visuals = themeVisualsForSkin(skin)
    return when (skin) {
        AppSkin.Pine -> Brush.verticalGradient(
            listOf(
                visuals.backgroundTop,
                Color(0xFFF0F5EF),
                visuals.backgroundBottom,
            ),
        )
        AppSkin.Pomelo -> Brush.verticalGradient(
            listOf(
                visuals.backgroundTop,
                Color(0xFFF8EFD9),
                visuals.backgroundBottom,
            ),
        )
        AppSkin.Harbor -> Brush.verticalGradient(
            listOf(
                visuals.backgroundTop,
                Color(0xFFF0F5F5),
                Color(0xFFE5EFF1),
                visuals.backgroundBottom,
            ),
        )
        AppSkin.Berry -> Brush.verticalGradient(
            listOf(
                visuals.backgroundTop,
                Color(0xFFF7ECEF),
                visuals.backgroundBottom,
            ),
        )
        AppSkin.Night -> Brush.verticalGradient(
            listOf(
                visuals.backgroundTop,
                Color(0xFF071B20),
                visuals.backgroundBottom,
            ),
        )
    }
}

@Composable
fun TicketboxTheme(
    skin: AppSkin,
    content: @Composable () -> Unit,
) {
    val view = LocalView.current
    val lightSystemBars = skin != AppSkin.Night
    if (!view.isInEditMode) {
        SideEffect {
            view.context.findActivity()?.configureTicketboxSystemBars(view, lightSystemBars)
        }
    }

    MaterialTheme(
        colorScheme = colorSchemeForSkin(skin),
        typography = MaterialTheme.typography,
        shapes = TicketboxShapes,
    ) {
        TicketboxAtmosphereBackground(skin = skin) {
            CompositionLocalProvider(
                LocalContentColor provides MaterialTheme.colorScheme.onBackground,
                LocalThemeVisuals provides themeVisualsForSkin(skin),
            ) {
                content()
            }
        }
    }
}

@Composable
fun TicketboxAtmosphereBackground(
    skin: AppSkin,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit = {},
) {
    val visuals = themeVisualsForSkin(skin)
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(backgroundBrushForSkin(skin)),
    ) {
        AtmosphereWash(
            modifier = Modifier
                .align(Alignment.TopStart)
                .offset(x = (-120).dp, y = (-120).dp)
                .size(520.dp),
            colors = listOf(
                visuals.warmMist.copy(alpha = if (skin == AppSkin.Night) 0.18f else 0.32f),
                Color.Transparent,
            ),
        )
        AtmosphereWash(
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .offset(x = 160.dp, y = (-30).dp)
                .size(560.dp),
            colors = listOf(
                visuals.coolMist.copy(alpha = if (skin == AppSkin.Night) 0.22f else 0.26f),
                Color.Transparent,
            ),
        )
        when (skin) {
            AppSkin.Pine -> {
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 96.dp, y = (-34).dp)
                        .size(420.dp),
                    colors = listOf(
                        Color(0xFF7EAD9F).copy(alpha = 0.26f),
                        Color.Transparent,
                    ),
                )
                MistBand(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .height(260.dp),
                    colors = listOf(
                        Color.Transparent,
                        Color(0xFFA6C2B1).copy(alpha = 0.22f),
                        Color(0xFF6C927C).copy(alpha = 0.16f),
                    ),
                )
            }
            AppSkin.Harbor -> {
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 76.dp, y = (-36).dp)
                        .size(330.dp),
                    colors = listOf(
                        Color(0xFF7FA7BF).copy(alpha = 0.36f),
                        Color.Transparent,
                    ),
                )
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.CenterEnd)
                        .offset(x = 104.dp)
                        .size(280.dp),
                    colors = listOf(
                        Color(0xFF9FC9D8).copy(alpha = 0.28f),
                        Color.Transparent,
                    ),
                )
                MistBand(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .height(260.dp),
                    colors = listOf(
                        Color.Transparent,
                        Color(0xFFB7D4DC).copy(alpha = 0.24f),
                        Color(0xFF7EA7BF).copy(alpha = 0.18f),
                    ),
                )
            }
            AppSkin.Night -> {
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 74.dp, y = (-36).dp)
                        .size(310.dp),
                    colors = listOf(
                        Color(0xFF2BB49A).copy(alpha = 0.22f),
                        Color.Transparent,
                    ),
                )
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .offset(x = (-88).dp, y = 88.dp)
                        .size(360.dp),
                    colors = listOf(
                        Color(0xFF245D78).copy(alpha = 0.26f),
                        Color.Transparent,
                    ),
                )
            }
            AppSkin.Pomelo -> {
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .offset(x = (-88).dp, y = (-42).dp)
                        .size(310.dp),
                    colors = listOf(
                        Color(0xFFFFCF7B).copy(alpha = 0.26f),
                        Color.Transparent,
                    ),
                )
                MistBand(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .height(240.dp),
                    colors = listOf(
                        Color.Transparent,
                        Color(0xFFE7D1A8).copy(alpha = 0.22f),
                    ),
                )
            }
            AppSkin.Berry -> {
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 64.dp, y = (-48).dp)
                        .size(300.dp),
                    colors = listOf(
                        Color(0xFFEAA2B5).copy(alpha = 0.26f),
                        Color.Transparent,
                    ),
                )
                MistBand(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .height(230.dp),
                    colors = listOf(
                        Color.Transparent,
                        Color(0xFFE5D8DC).copy(alpha = 0.20f),
                    ),
                )
            }
        }
        MistTextureOverlay(skin = skin, visuals = visuals)
        content()
    }
}

@Composable
private fun AtmosphereWash(
    modifier: Modifier,
    colors: List<Color>,
) {
    Box(modifier = modifier.background(Brush.radialGradient(colors)))
}

@Composable
private fun MistTextureOverlay(
    skin: AppSkin,
    visuals: ThemeVisuals,
) {
    val lineAlpha = if (skin == AppSkin.Night) 0.08f else 0.10f
    Canvas(modifier = Modifier.fillMaxSize()) {
        val lineColor = visuals.coolMist.copy(alpha = lineAlpha)
        repeat(10) { index ->
            val y = size.height * (0.12f + index * 0.085f)
            drawLine(
                color = lineColor,
                start = Offset(x = size.width * -0.10f, y = y),
                end = Offset(x = size.width * 1.10f, y = y + size.height * 0.035f),
                strokeWidth = 1.1f,
                cap = StrokeCap.Round,
            )
        }
    }
}

@Composable
private fun MistBand(
    modifier: Modifier,
    colors: List<Color>,
) {
    Box(modifier = modifier.background(Brush.verticalGradient(colors)))
}

private tailrec fun Context.findActivity(): Activity? {
    return when (this) {
        is Activity -> this
        is ContextWrapper -> baseContext.findActivity()
        else -> null
    }
}

@Suppress("DEPRECATION")
private fun Activity.configureTicketboxSystemBars(view: View, lightSystemBars: Boolean) {
    window.statusBarColor = AndroidColor.TRANSPARENT
    window.navigationBarColor = AndroidColor.TRANSPARENT
    WindowInsetsControllerCompat(window, view).apply {
        isAppearanceLightStatusBars = lightSystemBars
        isAppearanceLightNavigationBars = lightSystemBars
    }
}
