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
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalDashboardCardTokens
import com.ticketbox.ui.design.LocalGoalTokens
import com.ticketbox.ui.design.LocalSkeletonTokens
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalSwipeActionTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.ThemeVisuals
import com.ticketbox.ui.design.backgroundVisualsForSkin
import com.ticketbox.ui.design.chartTokensForSkin
import com.ticketbox.ui.design.dashboardCardTokensForSkin
import com.ticketbox.ui.design.goalTokensForSkin
import com.ticketbox.ui.design.skeletonTokensForSkin
import com.ticketbox.ui.design.stateTokensForSkin
import com.ticketbox.ui.design.swipeActionTokensForSkin
import com.ticketbox.ui.design.themeVisualsForSkin

private val PaperScheme = lightColorScheme(
    primary = Color(0xFF8A5A2B),
    onPrimary = Color(0xFFFBF8F1),
    primaryContainer = Color(0xFFEFE1CB),
    onPrimaryContainer = Color(0xFF5A3A14),
    secondary = Color(0xFF1C1A18),
    onSecondary = Color(0xFFFBF8F1),
    secondaryContainer = Color(0xFFECE7D8),
    onSecondaryContainer = Color(0xFF4A463F),
    tertiary = Color(0xFF4F6B3A),
    onTertiary = Color(0xFFFBF8F1),
    tertiaryContainer = Color(0xFFD9E0C4),
    onTertiaryContainer = Color(0xFF2E4220),
    background = Color(0xFFF3EFE6),
    onBackground = Color(0xFF1C1A18),
    surface = Color(0xFFFBF8F1),
    onSurface = Color(0xFF1C1A18),
    surfaceVariant = Color(0xFFF5F0E3),
    onSurfaceVariant = Color(0xFF4A463F),
    outline = Color(0x8F8A5A2B),
    outlineVariant = Color(0x428A5A2B),
    error = Color(0xFFA4361C),
    onError = Color(0xFFFBF8F1),
)

private val MonoScheme = lightColorScheme(
    primary = Color(0xFF0E0E0C),
    onPrimary = Color(0xFFFAFAF8),
    primaryContainer = Color(0xFFE3E2DD),
    onPrimaryContainer = Color(0xFF000000),
    secondary = Color(0xFF6F6E6A),
    onSecondary = Color(0xFFFAFAF8),
    secondaryContainer = Color(0xFFE3E2DD),
    onSecondaryContainer = Color(0xFF3A3A37),
    tertiary = Color(0xFF2C5036),
    onTertiary = Color(0xFFFAFAF8),
    tertiaryContainer = Color(0xFFD6E2D6),
    onTertiaryContainer = Color(0xFF15301C),
    background = Color(0xFFEDEDEA),
    onBackground = Color(0xFF0E0E0C),
    surface = Color(0xFFFAFAF8),
    onSurface = Color(0xFF0E0E0C),
    surfaceVariant = Color(0xFFF1F0ED),
    onSurfaceVariant = Color(0xFF3A3A37),
    outline = Color(0x990E0E0C),
    outlineVariant = Color(0x330E0E0C),
    error = Color(0xFF8E1D12),
    onError = Color(0xFFFAFAF8),
)

private val MidnightScheme = darkColorScheme(
    primary = Color(0xFFD6B487),
    onPrimary = Color(0xFF15171C),
    primaryContainer = Color(0xFF8A6A3E),
    onPrimaryContainer = Color(0xFFF0D9B3),
    secondary = Color(0xFFB89564),
    onSecondary = Color(0xFF15171C),
    secondaryContainer = Color(0xFF222530),
    onSecondaryContainer = Color(0xFFE9E7DF),
    tertiary = Color(0xFFA8B88A),
    onTertiary = Color(0xFF15171C),
    tertiaryContainer = Color(0xFF2C3220),
    onTertiaryContainer = Color(0xFFCCD9B8),
    background = Color(0xFF0C0D10),
    onBackground = Color(0xFFE9E7DF),
    surface = Color(0xFF15171C),
    onSurface = Color(0xFFE9E7DF),
    surfaceVariant = Color(0xFF1C1F25),
    onSurfaceVariant = Color(0xFFB8B4A8),
    outline = Color(0xAAD6B487),
    outlineVariant = Color(0x47D6B487),
    error = Color(0xFFD97757),
    onError = Color(0xFF15171C),
)

private val TicketboxShapes = Shapes(
    extraSmall = RoundedCornerShape(12.dp),
    small = RoundedCornerShape(16.dp),
    medium = RoundedCornerShape(22.dp),
    large = RoundedCornerShape(28.dp),
    extraLarge = RoundedCornerShape(34.dp),
)

fun colorSchemeForSkin(skin: AppSkin): ColorScheme {
    return when (skin) {
        AppSkin.Paper -> PaperScheme
        AppSkin.Mono -> MonoScheme
        AppSkin.Midnight -> MidnightScheme
    }
}

fun backgroundBrushForSkin(skin: AppSkin): Brush {
    return Brush.verticalGradient(backgroundVisualsForSkin(skin).baseGradient)
}

@Composable
fun TicketboxTheme(
    skin: AppSkin,
    currency: CurrencyCode = CurrencyCode.Default,
    currencyDisplay: CurrencyDisplay = CurrencyDisplay.Base,
    content: @Composable () -> Unit,
) {
    val view = LocalView.current
    val lightSystemBars = skin != AppSkin.Midnight
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
                LocalStateTokens provides stateTokensForSkin(skin),
                LocalChartTokens provides chartTokensForSkin(skin),
                LocalGoalTokens provides goalTokensForSkin(skin),
                LocalDashboardCardTokens provides dashboardCardTokensForSkin(skin),
                LocalSkeletonTokens provides skeletonTokensForSkin(skin),
                LocalSwipeActionTokens provides swipeActionTokensForSkin(skin),
                com.ticketbox.ui.design.LocalCurrencyCode provides currency,
                LocalCurrencyDisplay provides currencyDisplay,
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
    val backgroundVisuals = backgroundVisualsForSkin(skin)
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
                backgroundVisuals.topGlow.copy(alpha = backgroundVisuals.topGlowAlpha),
                Color.Transparent,
            ),
        )
        AtmosphereWash(
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .offset(x = 160.dp, y = (-30).dp)
                .size(560.dp),
            colors = listOf(
                backgroundVisuals.sideGlow.copy(alpha = backgroundVisuals.sideGlowAlpha),
                Color.Transparent,
            ),
        )
        when (skin) {
            AppSkin.Paper -> {
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 86.dp, y = (-36).dp)
                        .size(360.dp),
                    colors = listOf(
                        Color(0xFFEAD8B8).copy(alpha = 0.30f),
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
                        Color(0xFFE2D6C0).copy(alpha = 0.24f),
                        Color(0xFFC8B895).copy(alpha = 0.16f),
                    ),
                )
            }
            AppSkin.Mono -> {
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 76.dp, y = (-36).dp)
                        .size(320.dp),
                    colors = listOf(
                        Color(0xFFE0DFDA).copy(alpha = 0.28f),
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
                        Color(0xFFDADAD5).copy(alpha = 0.24f),
                    ),
                )
            }
            AppSkin.Midnight -> {
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 74.dp, y = (-36).dp)
                        .size(310.dp),
                    colors = listOf(
                        Color(0xFFD6B487).copy(alpha = 0.20f),
                        Color.Transparent,
                    ),
                )
                AtmosphereWash(
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .offset(x = (-88).dp, y = 88.dp)
                        .size(360.dp),
                    colors = listOf(
                        Color(0xFF8A6A3E).copy(alpha = 0.26f),
                        Color.Transparent,
                    ),
                )
            }
        }
        MistBand(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(210.dp),
            colors = backgroundVisuals.bottomMist,
        )
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
    val lineAlpha = if (skin == AppSkin.Midnight) 0.08f else 0.10f
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
