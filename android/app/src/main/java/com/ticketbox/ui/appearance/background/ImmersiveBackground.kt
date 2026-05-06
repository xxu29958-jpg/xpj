package com.ticketbox.ui.appearance.background

import android.graphics.BitmapFactory
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.shouldUseCustomBackground
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.theme.TicketboxAtmosphereBackground
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

enum class SurfaceRole {
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
    content: @Composable () -> Unit,
) {
    Box(modifier = Modifier.fillMaxSize()) {
        TicketboxBackgroundLayer(
            settings = backgroundSettings,
            skin = currentSkin,
            surfaceRole = surfaceRole,
        )
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(resolveGlobalScrim(backgroundSettings, currentSkin, surfaceRole)),
        )
        content()
    }
}

@Composable
fun TicketboxBackgroundLayer(
    settings: BackgroundSettings,
    skin: AppSkin,
    surfaceRole: SurfaceRole,
) {
    val depthScale by animateFloatAsState(
        targetValue = if (settings.enableParallax && !settings.reduceMotion) {
            when (surfaceRole) {
                SurfaceRole.Pending -> 1.05f
                SurfaceRole.Stats -> 1.045f
                SurfaceRole.Ledger -> 1.015f
                SurfaceRole.Edit -> 1.015f
                SurfaceRole.Settings -> 1.01f
                SurfaceRole.Auth -> 1.02f
            }
        } else {
            1f
        },
        animationSpec = tween(durationMillis = if (settings.reduceMotion) 0 else 220),
        label = "backgroundDepthScale",
    )

    Box(
        modifier = Modifier.fillMaxSize(),
    ) {
        TicketboxAtmosphereBackground(skin = skin)
        when (settings.source) {
            BackgroundSource.ThemeDefault -> Unit
            BackgroundSource.BuiltIn -> {
                val preset = BackgroundCatalog.find(settings.builtInBackgroundId)
                if (preset != null) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .graphicsLayer {
                                scaleX = depthScale
                                scaleY = depthScale
                            }
                            .alpha(resolveBackgroundAlpha(settings.immersionMode, surfaceRole))
                            .background(
                                Brush.verticalGradient(
                                    preset.gradientColors.map { color -> Color(color) },
                                ),
                            ),
                    )
                }
            }
            BackgroundSource.CustomImage -> {
                val customImagePath = settings.customImagePath
                val shouldShowCustom = settings.source == BackgroundSource.CustomImage &&
                    !customImagePath.isNullOrBlank() &&
                    File(customImagePath).isFile
                if (shouldShowCustom) {
                    val image = rememberBackgroundImage(customImagePath)
                    image?.let {
                        Image(
                            bitmap = it,
                            contentDescription = null,
                            contentScale = ContentScale.Crop,
                            alignment = alignmentForCropMode(settings.cropMode),
                            modifier = Modifier
                                .fillMaxSize()
                                .graphicsLayer {
                                    scaleX = depthScale
                                    scaleY = depthScale
                                }
                                .alpha(resolveBackgroundAlpha(settings.immersionMode, surfaceRole)),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun rememberBackgroundImage(path: String?): ImageBitmap? {
    var image by remember(path) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(path) {
        image = null
        val cleanPath = path?.takeIf { it.isNotBlank() } ?: return@LaunchedEffect
        image = withContext(Dispatchers.IO) {
            decodeBackgroundImage(cleanPath)
        }
    }
    return image
}

private fun alignmentForCropMode(mode: BackgroundCropMode): Alignment {
    return when (mode) {
        BackgroundCropMode.Top -> Alignment.TopCenter
        BackgroundCropMode.Center -> Alignment.Center
        BackgroundCropMode.Bottom -> Alignment.BottomCenter
    }
}

private fun decodeBackgroundImage(path: String): ImageBitmap? {
    val bounds = BitmapFactory.Options().apply {
        inJustDecodeBounds = true
    }
    BitmapFactory.decodeFile(path, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
        return null
    }
    val options = BitmapFactory.Options().apply {
        inSampleSize = calculateInSampleSize(
            width = bounds.outWidth,
            height = bounds.outHeight,
            maxSide = MAX_BACKGROUND_SIDE,
        )
    }
    return BitmapFactory.decodeFile(path, options)?.asImageBitmap()
}

private fun calculateInSampleSize(width: Int, height: Int, maxSide: Int): Int {
    var sampleSize = 1
    val largestSide = maxOf(width, height)
    while (largestSide / sampleSize > maxSide) {
        sampleSize *= 2
    }
    return sampleSize.coerceAtLeast(1)
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
        SurfaceRole.Pending -> 1.00f
        SurfaceRole.Stats -> 0.92f
        SurfaceRole.Ledger -> 0.52f
        SurfaceRole.Edit -> 0.42f
        SurfaceRole.Settings -> 0.36f
        SurfaceRole.Auth -> 0.45f
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
    val roleExtra = when (role) {
        SurfaceRole.Pending -> 0.00f
        SurfaceRole.Stats -> 0.04f
        SurfaceRole.Ledger -> 0.16f
        SurfaceRole.Edit -> 0.18f
        SurfaceRole.Settings -> 0.20f
        SurfaceRole.Auth -> 0.14f
    }
    return (base + roleExtra).coerceIn(0.12f, 0.70f)
}

fun resolveCardContainerAlpha(
    mode: ImmersionMode,
    role: SurfaceRole,
): Float {
    return when (role) {
        SurfaceRole.Pending -> when (mode) {
            ImmersionMode.Atmosphere -> 0.76f
            ImmersionMode.Balanced -> 0.84f
            ImmersionMode.Focus -> 0.92f
        }
        SurfaceRole.Stats -> when (mode) {
            ImmersionMode.Atmosphere -> 0.74f
            ImmersionMode.Balanced -> 0.82f
            ImmersionMode.Focus -> 0.92f
        }
        SurfaceRole.Ledger -> when (mode) {
            ImmersionMode.Atmosphere -> 0.90f
            ImmersionMode.Balanced -> 0.95f
            ImmersionMode.Focus -> 0.98f
        }
        SurfaceRole.Edit,
        SurfaceRole.Settings,
        SurfaceRole.Auth -> when (mode) {
            ImmersionMode.Atmosphere -> 0.90f
            ImmersionMode.Balanced -> 0.94f
            ImmersionMode.Focus -> 0.98f
        }
    }
}

fun resolveGlobalScrim(
    settings: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
): Brush {
    val backgroundVisible = when (settings.source) {
        BackgroundSource.ThemeDefault -> false
        BackgroundSource.BuiltIn -> BackgroundCatalog.find(settings.builtInBackgroundId) != null
        BackgroundSource.CustomImage -> shouldUseCustomBackground(settings) { path -> File(path).isFile }
    }
    val isDarkBackground = skin == AppSkin.Night
    val scrimAlpha = if (backgroundVisible) {
        resolveScrimAlpha(settings.immersionMode, role)
    } else {
        when (role) {
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
    val bottom = if (isDarkBackground) {
        Color.Black.copy(alpha = (scrimAlpha + 0.12f).coerceAtMost(0.72f))
    } else {
        Color(0xFFF7F8F4).copy(alpha = (scrimAlpha + 0.16f).coerceAtMost(0.78f))
    }
    return Brush.verticalGradient(
        colors = listOf(
            scrim,
            bottom,
        ),
    )
}

private const val MAX_BACKGROUND_SIDE = 2160
