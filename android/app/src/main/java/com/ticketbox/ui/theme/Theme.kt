package com.ticketbox.ui.theme

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.graphics.Color as AndroidColor
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.tween
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
import androidx.compose.ui.graphics.BlendMode
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
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalDashboardCardTokens
import com.ticketbox.ui.design.LocalGoalTokens
import com.ticketbox.ui.design.LocalSkeletonTokens
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalSwipeActionTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.SkeletonTokens
import com.ticketbox.ui.design.ThemeVisuals
import com.ticketbox.ui.design.backgroundVisualsForSkin
import com.ticketbox.ui.design.chartTokensForSkin
import com.ticketbox.ui.design.dashboardCardTokensForSkin
import com.ticketbox.ui.design.goalTokensForSkin
import com.ticketbox.ui.design.skeletonTokensForSkin
import com.ticketbox.ui.design.stateTokensForSkin
import com.ticketbox.ui.design.swipeActionTokensForSkin
import com.ticketbox.ui.design.themeVisualsForSkin
import com.valentinilk.shimmer.LocalShimmerTheme
import com.valentinilk.shimmer.ShimmerTheme
import com.valentinilk.shimmer.defaultShimmerTheme

// Material3 colorScheme —— 核心槽位从 ThemeVisuals / StateTokens 派生(单一真相源,
// 刷新调色板时自动跟随,不再静默漂移)。仅 M3 专属的 on-container 对比文字 /
// tertiaryContainer 保留字面量(它们不对应任何共享 token,是 M3 的可读性计算值);
// outline 系列用 primary 加 alpha 派生,RGB 跟随品牌色。
// 取值保真性由 release_audit 的 token-parity lane + 提交前脚本逐槽位核对(0 漂移)。
private val PaperScheme = run {
    val v = themeVisualsForSkin(AppSkin.Paper)
    val s = stateTokensForSkin(AppSkin.Paper)
    lightColorScheme(
        primary = v.primary,
        onPrimary = v.textOnPrimary,
        primaryContainer = v.brandPrimaryBg,
        onPrimaryContainer = Color(0xFF5A3A14),
        secondary = v.textDefault,
        onSecondary = v.textOnPrimary,
        secondaryContainer = s.neutral.bg,
        onSecondaryContainer = v.textMuted,
        tertiary = s.success.fg,
        onTertiary = v.textOnPrimary,
        tertiaryContainer = s.success.bg,
        onTertiaryContainer = Color(0xFF2E4220),
        background = v.backgroundBottom,
        onBackground = v.textDefault,
        surface = v.solidCard,
        onSurface = v.textDefault,
        surfaceVariant = v.surfaceSunken,
        onSurfaceVariant = v.textMuted,
        outline = v.primary.copy(alpha = 0x8F / 255f),
        outlineVariant = v.primary.copy(alpha = 0x42 / 255f),
        error = s.danger.fg,
        onError = v.textOnPrimary,
    )
}

private val MonoScheme = run {
    val v = themeVisualsForSkin(AppSkin.Mono)
    val s = stateTokensForSkin(AppSkin.Mono)
    lightColorScheme(
        primary = v.primary,
        onPrimary = v.textOnPrimary,
        primaryContainer = v.brandPrimaryBg,
        onPrimaryContainer = v.primaryDark,
        secondary = v.accent,
        onSecondary = v.textOnPrimary,
        secondaryContainer = s.neutral.bg,
        onSecondaryContainer = v.textMuted,
        tertiary = s.success.fg,
        onTertiary = v.textOnPrimary,
        tertiaryContainer = s.success.bg,
        onTertiaryContainer = Color(0xFF15301C),
        background = v.backgroundBottom,
        onBackground = v.textDefault,
        surface = v.solidCard,
        onSurface = v.textDefault,
        surfaceVariant = v.surfaceSunken,
        onSurfaceVariant = v.textMuted,
        outline = v.primary.copy(alpha = 0x99 / 255f),
        outlineVariant = v.primary.copy(alpha = 0x33 / 255f),
        error = s.danger.fg,
        onError = v.textOnPrimary,
    )
}

private val MidnightScheme = run {
    val v = themeVisualsForSkin(AppSkin.Midnight)
    val s = stateTokensForSkin(AppSkin.Midnight)
    darkColorScheme(
        primary = v.primary,
        onPrimary = v.textOnPrimary,
        primaryContainer = v.accent,
        onPrimaryContainer = Color(0xFFF0D9B3),
        secondary = v.primaryDark,
        onSecondary = v.textOnPrimary,
        secondaryContainer = v.surfaceRaised,
        onSecondaryContainer = v.textDefault,
        tertiary = s.success.fg,
        onTertiary = v.textOnPrimary,
        tertiaryContainer = Color(0xFF2C3220),
        onTertiaryContainer = Color(0xFFCCD9B8),
        background = v.backgroundBottom,
        onBackground = v.textDefault,
        surface = v.solidCard,
        onSurface = v.textDefault,
        surfaceVariant = v.surfaceSunken,
        onSurfaceVariant = v.textMuted,
        outline = v.primary.copy(alpha = 0xAA / 255f),
        outlineVariant = v.primary.copy(alpha = 0x47 / 255f),
        error = s.danger.fg,
        onError = v.textOnPrimary,
    )
}

// M3 Shapes 派生自 [AppRadius] —— 不再硬编码 dp,与三端 design scale 真同步。
// 映射规则:
//   extraSmall (M3 Snackbar/Tooltip)     → AppRadius.extraSmall  ( 8dp)
//   small      (M3 Button/Chip-like)     → AppRadius.small       (12dp)
//   medium     (M3 Card)                 → AppRadius.medium      (20dp)
//   large      (M3 BottomSheet)          → AppRadius.large       (28dp)
//   extraLarge (M3 Dialog/Hero)          → AppRadius.hero        (36dp)
private val TicketboxShapes = Shapes(
    extraSmall = RoundedCornerShape(AppRadius.extraSmall),
    small      = RoundedCornerShape(AppRadius.small),
    medium     = RoundedCornerShape(AppRadius.medium),
    large      = RoundedCornerShape(AppRadius.large),
    extraLarge = RoundedCornerShape(AppRadius.hero),
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

    val skeletonTokens = skeletonTokensForSkin(skin)
    MaterialTheme(
        colorScheme = colorSchemeForSkin(skin),
        typography = TicketboxTypography,
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
                LocalSkeletonTokens provides skeletonTokens,
                LocalShimmerTheme provides shimmerThemeFor(skeletonTokens),
                LocalSwipeActionTokens provides swipeActionTokensForSkin(skin),
                com.ticketbox.ui.design.LocalCurrencyCode provides currency,
                LocalCurrencyDisplay provides currencyDisplay,
            ) {
                content()
            }
        }
    }
}

/**
 * 由 [SkeletonTokens] 派生 valentinilk shimmer 主题，让骨架扫光真正消费三端 token：
 *
 * - 扫光带改画 tokens.shine 渐变（midnight 暖金、paper/mono 白光），blendMode 用
 *   [BlendMode.SrcOver]——库默认的 DstIn 是 alpha 蒙版（骨架大部分时间被压到
 *   25%×base，midnight 6% 底直接被压到不可见），SrcOver 才是"底色常驻 + 光带扫过"。
 * - 节奏改 [SkeletonTokens.shimmerDurationMillis]（1200ms）连续线性扫光，去掉库默认
 *   800ms+1500ms 间歇，与 /web、/owner 的 `--motion-shimmer` 一致。
 */
private fun shimmerThemeFor(tokens: SkeletonTokens): ShimmerTheme = defaultShimmerTheme.copy(
    animationSpec = infiniteRepeatable(
        animation = tween(
            durationMillis = tokens.shimmerDurationMillis,
            easing = LinearEasing,
        ),
        repeatMode = RepeatMode.Restart,
    ),
    blendMode = BlendMode.SrcOver,
    shaderColors = listOf(
        tokens.shine.copy(alpha = 0f),
        tokens.shine,
        tokens.shine.copy(alpha = 0f),
    ),
)

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
