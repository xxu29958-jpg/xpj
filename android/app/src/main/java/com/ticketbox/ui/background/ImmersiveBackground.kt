package com.ticketbox.ui.background

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
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.shouldUseCustomBackground
import com.ticketbox.ui.theme.backgroundBrushForSkin
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

enum class SurfaceRole {
    Home,
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
    currentSurfaceRole: SurfaceRole,
    content: @Composable () -> Unit,
) {
    Box(modifier = Modifier.fillMaxSize()) {
        TicketboxBackgroundLayer(
            settings = backgroundSettings,
            skin = currentSkin,
            surfaceRole = currentSurfaceRole,
        )
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(resolveGlobalScrim(backgroundSettings, currentSkin, currentSurfaceRole)),
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
                SurfaceRole.Home -> 1.05f
                SurfaceRole.Stats -> 1.045f
                SurfaceRole.Ledger -> 1.03f
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
        modifier = Modifier
            .fillMaxSize()
            .background(backgroundBrushForSkin(skin)),
    ) {
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
        SurfaceRole.Home -> 1.00f
        SurfaceRole.Stats -> 0.92f
        SurfaceRole.Ledger -> 0.68f
        SurfaceRole.Edit -> 0.42f
        SurfaceRole.Settings -> 0.36f
        SurfaceRole.Auth -> 0.45f
    }
    return (base * roleFactor).coerceIn(0.18f, 0.90f)
}

fun resolveGlobalScrim(
    settings: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
): Brush {
    val customVisible = shouldUseCustomBackground(settings) { path -> File(path).isFile }
    val isDarkSkin = skin == AppSkin.Night
    val scrimAlpha = when (role) {
        SurfaceRole.Home -> if (customVisible) 0.18f else 0.02f
        SurfaceRole.Stats -> if (customVisible) 0.22f else 0.04f
        SurfaceRole.Ledger -> if (customVisible) 0.38f else 0.08f
        SurfaceRole.Edit -> if (customVisible) 0.56f else 0.12f
        SurfaceRole.Settings -> if (customVisible) 0.60f else 0.12f
        SurfaceRole.Auth -> if (customVisible) 0.52f else 0.10f
    }
    val scrim = if (isDarkSkin) {
        Color.Black.copy(alpha = scrimAlpha)
    } else {
        Color.White.copy(alpha = scrimAlpha)
    }
    val bottom = if (isDarkSkin) {
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
