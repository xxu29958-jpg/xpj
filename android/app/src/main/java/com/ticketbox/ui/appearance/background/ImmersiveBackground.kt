package com.ticketbox.ui.appearance.background

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.shouldUseCustomBackground
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.design.themeVisualsForSkin
import com.ticketbox.ui.theme.TicketboxAtmosphereBackground
import java.io.File

enum class SurfaceRole {
    Today,
    Pending,
    Ledger,
    Stats,
    Edit,
    Settings,
    Auth,
}

@Composable
fun ImmersiveBackgroundScaffold(
    backgroundSettings: BackgroundSettings,
    currentSkin: AppSkin,
    surfaceRole: SurfaceRole,
    canvasText: CanvasTextDemand = CanvasTextDemand.Body,
    content: @Composable () -> Unit,
) {
    val photo = rememberBackgroundImage(customPhotoPath(backgroundSettings))
    val canvasState = remember { CanvasPhotoState() }
    SideEffect {
        canvasState.photoActive = photo != null
        canvasState.immersion = backgroundSettings.immersionMode
    }
    Box(modifier = Modifier.fillMaxSize()) {
        BackgroundCanvas(backgroundSettings, currentSkin, surfaceRole, photo, CanvasLayout(canvasText, canvasState.headerBandPx))
        CompositionLocalProvider(LocalCanvasPhotoState provides canvasState) { content() }
    }
}

/**
 * 背景编辑器的预览舞台：与 [ImmersiveBackgroundScaffold] 同一张背景画布（图片层 +
 * 按图片实测的可读遮罩 + 底部导航保护），只是承载在编辑面容器内。可承载明确
 * 标注的组件样例；不把示例金额当成业务事实。
 */
@Composable
fun BackgroundPreviewStage(
    settings: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit = {},
) {
    val photo = rememberBackgroundImage(customPhotoPath(settings))
    // The stage publishes the same canvas state as the shell, so a domain header previewed inside
    // it opens the same photo window and is measured the same way.
    val canvasState = remember { CanvasPhotoState() }
    SideEffect {
        canvasState.photoActive = photo != null
        canvasState.immersion = settings.immersionMode
    }
    Box(modifier = modifier) {
        Box(Modifier.matchParentSize()) {
            BackgroundCanvas(settings, skin, role, photo, CanvasLayout(headerBandPx = canvasState.headerBandPx))
        }
        CompositionLocalProvider(LocalCanvasPhotoState provides canvasState) { content() }
    }
}

@Composable
internal fun BoxScope.BottomReadabilityScrim(
    settings: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
) {
    val visuals = themeVisualsForSkin(skin)
    val backgroundVisible = backgroundIsVisible(settings)
    val roleAlpha = when (role) {
        SurfaceRole.Today -> 0.79f
        SurfaceRole.Pending -> 0.80f
        SurfaceRole.Stats -> 0.78f
        SurfaceRole.Ledger -> 0.86f
        SurfaceRole.Edit -> 0.90f
        SurfaceRole.Settings -> 0.88f
        SurfaceRole.Auth -> 0.84f
    }
    // A decoded photo has its own measured navigation protection in BackgroundCanvas.
    val alpha = when {
        backgroundVisible -> roleAlpha
        else -> roleAlpha * 0.42f
    }
    val scrimHeight = 260.dp
    val bottomColor = if (skin == AppSkin.Midnight) {
        Color(0xFF061015).copy(alpha = alpha)
    } else {
        visuals.backgroundBottom.copy(alpha = alpha)
    }
    Box(
        modifier = Modifier
            .align(Alignment.BottomCenter)
            .fillMaxWidth()
            .height(scrimHeight)
            .background(
                Brush.verticalGradient(
                    colors = listOf(
                        Color.Transparent,
                        bottomColor.copy(alpha = alpha * 0.48f),
                        bottomColor,
                    ),
                ),
            ),
    )
}

@Composable
internal fun TicketboxBackgroundLayer(
    settings: BackgroundSettings,
    skin: AppSkin,
    surfaceRole: SurfaceRole,
    photo: DecodedBackground?,
) {
    val depthScale by animateFloatAsState(
        targetValue = if (settings.enableParallax && !settings.reduceMotion) parallaxDepthScale(surfaceRole) else 1f,
        animationSpec = tween(durationMillis = if (settings.reduceMotion) 0 else 220),
        label = "backgroundDepthScale",
    )
    Box(modifier = Modifier.fillMaxSize()) {
        TicketboxAtmosphereBackground(skin = skin)
        when (settings.source) {
            BackgroundSource.ThemeDefault -> Unit
            BackgroundSource.BuiltIn -> BackgroundCatalog.find(settings.builtInBackgroundId)?.let { preset ->
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .graphicsLayer {
                            scaleX = depthScale
                            scaleY = depthScale
                        }
                        .alpha(resolveBackgroundAlpha(settings.immersionMode, surfaceRole))
                        .background(Brush.verticalGradient(preset.gradientColors.map { color -> Color(color) })),
                )
            }
            BackgroundSource.CustomImage -> photo?.let { PhotoLayer(it, settings.transform) { depthScale } }
        }
    }
}

private fun parallaxDepthScale(role: SurfaceRole): Float = when (role) {
    SurfaceRole.Today -> 1.04f
    SurfaceRole.Pending -> 1.05f
    SurfaceRole.Stats -> 1.045f
    SurfaceRole.Ledger -> 1.015f
    SurfaceRole.Edit -> 1.015f
    SurfaceRole.Settings -> 1.01f
    SurfaceRole.Auth -> 1.02f
}

fun resolveBackgroundAlpha(
    mode: ImmersionMode,
    role: SurfaceRole,
): Float {
    val base = when (mode) {
        ImmersionMode.Atmosphere -> 0.88f
        ImmersionMode.Balanced -> 0.62f
        ImmersionMode.Focus -> 0.32f
    }
    val roleFactor = when (role) {
        SurfaceRole.Today -> 0.86f
        SurfaceRole.Pending -> 1.00f
        SurfaceRole.Stats -> 0.92f
        // 全局背景批:上调日常页系数——背景是用户设置的全局氛围,
        // 不能盖到等于没设;卡片/遮罩仍保内容可读(Focus 档不变)。
        SurfaceRole.Ledger -> 0.72f
        SurfaceRole.Edit -> 0.60f
        SurfaceRole.Settings -> 0.62f
        SurfaceRole.Auth -> 0.60f
    }
    return (base * roleFactor).coerceIn(0.18f, 0.90f)
}

fun resolveScrimAlpha(
    mode: ImmersionMode,
    role: SurfaceRole,
): Float {
    val base = when (mode) {
        ImmersionMode.Atmosphere -> 0.18f
        ImmersionMode.Balanced -> 0.30f
        ImmersionMode.Focus -> 0.48f
    }
    return (base + scrimRoleExtra(role)).coerceIn(0.12f, 0.70f)
}

private fun scrimRoleExtra(role: SurfaceRole): Float = when (role) {
    SurfaceRole.Today -> 0.02f
    SurfaceRole.Pending -> 0.00f
    SurfaceRole.Stats -> 0.04f
    SurfaceRole.Ledger -> 0.16f
    SurfaceRole.Edit -> 0.18f
    SurfaceRole.Settings -> 0.20f
    SurfaceRole.Auth -> 0.14f
}

fun resolveGlobalScrim(
    settings: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
): Brush {
    val backgroundVisible = backgroundIsVisible(settings)
    val isDarkBackground = skin == AppSkin.Midnight
    // A decoded user photo is veiled by BackgroundCanvas; this curve serves built-in artwork and
    // the theme canvas (including the moment before a photo has decoded).
    val scrimAlpha = if (backgroundVisible && settings.source == BackgroundSource.BuiltIn) {
        resolveScrimAlpha(settings.immersionMode, role)
    } else {
        when (role) {
            SurfaceRole.Today -> 0.03f
            SurfaceRole.Pending -> 0.02f
            SurfaceRole.Stats -> 0.04f
            SurfaceRole.Ledger -> 0.14f
            SurfaceRole.Edit -> 0.12f
            SurfaceRole.Settings -> 0.12f
            SurfaceRole.Auth -> 0.10f
        }
    }
    val scrim = if (isDarkBackground) {
        Color.Black.copy(alpha = scrimAlpha)
    } else {
        Color.White.copy(alpha = scrimAlpha)
    }
    val bottomAlphaLimit = if (isDarkBackground) {
        0.72f
    } else {
        0.78f
    }
    val bottom = if (isDarkBackground) {
        Color.Black.copy(alpha = (scrimAlpha + 0.12f).coerceAtMost(bottomAlphaLimit))
    } else {
        Color(0xFFF7F8F4).copy(alpha = (scrimAlpha + 0.16f).coerceAtMost(bottomAlphaLimit))
    }
    return Brush.verticalGradient(
        colors = listOf(
            scrim,
            bottom,
        ),
    )
}

private fun backgroundIsVisible(settings: BackgroundSettings): Boolean = when (settings.source) {
    BackgroundSource.ThemeDefault -> false
    BackgroundSource.BuiltIn -> BackgroundCatalog.find(settings.builtInBackgroundId) != null
    BackgroundSource.CustomImage -> shouldUseCustomBackground(settings) { path -> File(path).isFile }
}
