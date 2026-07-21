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
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
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
import androidx.compose.foundation.shape.RoundedCornerShape
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
import com.ticketbox.ui.design.LocalGoalTokens
import com.ticketbox.ui.design.LocalSkeletonTokens
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.ui.design.LocalSwipeActionTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.SkeletonTokens
import com.ticketbox.ui.design.backgroundVisualsForSkin
import com.ticketbox.ui.design.chartTokensForSkin
import com.ticketbox.ui.design.goalTokensForSkin
import com.ticketbox.ui.design.skeletonTokensForSkin
import com.ticketbox.ui.design.statsTokensForSkin
import com.ticketbox.ui.design.stateTokensForSkin
import com.ticketbox.ui.design.swipeActionTokensForSkin
import com.ticketbox.ui.design.themeVisualsForSkin
import com.valentinilk.shimmer.LocalShimmerTheme
import com.valentinilk.shimmer.ShimmerTheme
import com.valentinilk.shimmer.defaultShimmerTheme

// Material3 colorScheme —— 核心槽位从 ThemeVisuals / StateTokens 派生(单一真相源,
// 刷新调色板时自动跟随,不再静默漂移)。M3 的 surface-container / inverse /
// error-container 槽位也显式映射，避免底部面板、弹窗回落到默认紫调。
// 取值保真性由 release_audit 的 token-parity lane + 提交前脚本逐槽位核对(0 漂移)。
private val PaperScheme = run {
    val v = themeVisualsForSkin(AppSkin.Paper)
    val s = stateTokensForSkin(AppSkin.Paper)
    lightColorScheme(
        primary = v.primary,
        onPrimary = v.textOnPrimary,
        primaryContainer = v.brandPrimaryBg,
        onPrimaryContainer = v.primaryDark,
        secondary = v.textDefault,
        onSecondary = v.textOnPrimary,
        secondaryContainer = s.neutral.bg,
        onSecondaryContainer = v.textMuted,
        tertiary = s.success.fg,
        onTertiary = v.textOnPrimary,
        tertiaryContainer = s.success.bg,
        onTertiaryContainer = s.success.fg,
        background = v.backgroundBottom,
        onBackground = v.textDefault,
        surface = v.solidCard,
        onSurface = v.textDefault,
        surfaceVariant = v.surfaceSunken,
        onSurfaceVariant = v.textMuted,
        surfaceTint = v.primary,
        inverseSurface = v.textDefault,
        inverseOnSurface = v.solidCard,
        surfaceBright = v.solidCard,
        surfaceDim = v.backgroundBottom,
        surfaceContainerLowest = v.solidCard,
        surfaceContainerLow = v.backgroundTop,
        surfaceContainer = v.surfaceSunken,
        surfaceContainerHigh = v.receiptStub.footer,
        surfaceContainerHighest = v.receiptStub.border,
        outline = v.textMeta,
        outlineVariant = v.receiptStub.border,
        error = s.danger.fg,
        onError = v.textOnPrimary,
        errorContainer = s.danger.bg,
        onErrorContainer = s.danger.fg,
        scrim = Color.Black,
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
        onTertiaryContainer = s.success.fg,
        background = v.backgroundBottom,
        onBackground = v.textDefault,
        surface = v.solidCard,
        onSurface = v.textDefault,
        surfaceVariant = v.surfaceSunken,
        onSurfaceVariant = v.textMuted,
        surfaceTint = v.primary,
        inverseSurface = v.textDefault,
        inverseOnSurface = v.solidCard,
        surfaceBright = v.solidCard,
        surfaceDim = v.backgroundBottom,
        surfaceContainerLowest = v.solidCard,
        surfaceContainerLow = v.backgroundTop,
        surfaceContainer = v.surfaceSunken,
        surfaceContainerHigh = v.receiptStub.footer,
        surfaceContainerHighest = v.receiptStub.border,
        outline = v.textMeta,
        outlineVariant = v.receiptStub.border,
        error = s.danger.fg,
        onError = v.textOnPrimary,
        errorContainer = s.danger.bg,
        onErrorContainer = s.danger.fg,
        scrim = Color.Black,
    )
}

private val MidnightScheme = run {
    val v = themeVisualsForSkin(AppSkin.Midnight)
    val s = stateTokensForSkin(AppSkin.Midnight)
    darkColorScheme(
        primary = v.primary,
        onPrimary = v.textOnPrimary,
        primaryContainer = v.brandPrimaryBg,
        onPrimaryContainer = v.primary,
        secondary = v.primaryDark,
        onSecondary = v.textOnPrimary,
        secondaryContainer = v.surfaceRaised,
        onSecondaryContainer = v.textDefault,
        tertiary = s.success.fg,
        onTertiary = v.textOnPrimary,
        tertiaryContainer = s.success.bg,
        onTertiaryContainer = s.success.fg,
        background = v.backgroundBottom,
        onBackground = v.textDefault,
        surface = v.solidCard,
        onSurface = v.textDefault,
        surfaceVariant = v.surfaceSunken,
        onSurfaceVariant = v.textMuted,
        surfaceTint = v.primary,
        inverseSurface = v.textDefault,
        inverseOnSurface = v.backgroundBottom,
        surfaceBright = v.surfaceRaised,
        surfaceDim = v.backgroundBottom,
        surfaceContainerLowest = v.backgroundBottom,
        surfaceContainerLow = v.solidCard,
        surfaceContainer = v.surfaceSunken,
        surfaceContainerHigh = v.surfaceRaised,
        surfaceContainerHighest = v.receiptStub.footer,
        outline = v.textMeta,
        outlineVariant = v.receiptStub.border,
        error = s.danger.fg,
        onError = v.textOnPrimary,
        errorContainer = s.danger.bg,
        onErrorContainer = s.danger.fg,
        scrim = Color.Black,
    )
}

// M3 Shapes 派生自 [AppRadius] —— 不再硬编码 dp,与三端 design scale 真同步。
// 映射规则:
//   extraSmall (M3 Snackbar/Tooltip)     → AppRadius.extraSmall  ( 6dp)
//   small      (M3 Button/Chip-like)     → AppRadius.small       (10dp)
//   medium     (M3 Card)                 → AppRadius.medium      (14dp)
//   large      (M3 BottomSheet)          → AppRadius.large       (18dp)
//   extraLarge (M3 Dialog/Hero)          → AppRadius.hero        (20dp)
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
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background),
        ) {
            CompositionLocalProvider(
                LocalContentColor provides MaterialTheme.colorScheme.onBackground,
                LocalThemeVisuals provides themeVisualsForSkin(skin),
                LocalStateTokens provides stateTokensForSkin(skin),
                LocalChartTokens provides chartTokensForSkin(skin),
                LocalGoalTokens provides goalTokensForSkin(skin),
                LocalStatsTokens provides statsTokensForSkin(skin),
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
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(backgroundBrushForSkin(skin)),
    ) {
        content()
    }
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
