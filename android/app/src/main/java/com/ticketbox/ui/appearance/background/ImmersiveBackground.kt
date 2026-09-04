package com.ticketbox.ui.appearance.background

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.exifinterface.media.ExifInterface
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.shouldUseCustomBackground
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.design.themeVisualsForSkin
import com.ticketbox.ui.theme.TicketboxAtmosphereBackground
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
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
        BottomReadabilityScrim(
            settings = backgroundSettings,
            skin = currentSkin,
            role = surfaceRole,
        )
        content()
    }
}

/**
 * 背景编辑器的预览舞台：真实三层渲染（背景层 + 全局 scrim + 底部可读遮罩），
 * 与 [ImmersiveBackgroundScaffold] 同一管线，只是承载在编辑面容器内。
 * 只承诺「背景与遮罩」预览，不以样卡冒充具体业务页面；应用后的全局效果
 * 由真实五域 / 设置 / 登录页验收。
 */
@Composable
fun BackgroundPreviewStage(
    settings: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit = {},
) {
    Box(modifier = modifier) {
        TicketboxBackgroundLayer(settings = settings, skin = skin, surfaceRole = role)
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(resolveGlobalScrim(settings, skin, role)),
        )
        BottomReadabilityScrim(settings = settings, skin = skin, role = role)
        content()
    }
}

@Composable
private fun BoxScope.BottomReadabilityScrim(
    settings: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
) {
    val visuals = themeVisualsForSkin(skin)
    val backgroundVisible = when (settings.source) {
        BackgroundSource.ThemeDefault -> false
        BackgroundSource.BuiltIn -> BackgroundCatalog.find(settings.builtInBackgroundId) != null
        BackgroundSource.CustomImage -> shouldUseCustomBackground(settings) { path -> File(path).isFile }
    }
    val roleAlpha = when (role) {
        SurfaceRole.Today -> 0.79f
        SurfaceRole.Pending -> 0.80f
        SurfaceRole.Stats -> 0.78f
        SurfaceRole.Ledger -> 0.86f
        SurfaceRole.Edit -> 0.90f
        SurfaceRole.Settings -> 0.88f
        SurfaceRole.Auth -> 0.84f
    }
    // 全局背景批:custom 图与内置同一规线(旧 360dp/+0.10/封顶 0.96 会把用户图
    // 埋到等于没设);只保留轻微加深,保底部导航区可读。
    val alpha = when {
        settings.source == BackgroundSource.CustomImage && backgroundVisible -> (roleAlpha + 0.04f).coerceAtMost(0.88f)
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
fun TicketboxBackgroundLayer(
    settings: BackgroundSettings,
    skin: AppSkin,
    surfaceRole: SurfaceRole,
) {
    val depthScale by animateFloatAsState(
        targetValue = if (settings.enableParallax && !settings.reduceMotion) {
            when (surfaceRole) {
                SurfaceRole.Today -> 1.04f
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
                    image?.let { bitmap ->
                        // 自由构图渲染:Image 层尺寸 = 完整绘制尺寸(超出视口),
                        // 外层 clipToBounds;平移在视口内移动 oversized 层,露出的是
                        // 原图其余部分。不能用 ContentScale.Crop + graphicsLayer 平移
                        // 已裁到视口的层——那只会露底。
                        val transform = settings.transform
                        Box(
                            modifier = Modifier
                                .fillMaxSize()
                                .clipToBounds(),
                        ) {
                            BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
                                val viewport = IntSize(constraints.maxWidth, constraints.maxHeight)
                                val imageSize = IntSize(bitmap.width, bitmap.height)
                                val density = LocalDensity.current
                                val coverScale = BackgroundTransformGeometry.cropBaseScale(
                                    viewport = viewport,
                                    image = imageSize,
                                )
                                val drawnWidth = bitmap.width * coverScale * transform.scale
                                val drawnHeight = bitmap.height * coverScale * transform.scale
                                // 视差 depthScale 只放大层、不纳入平移余量:保证任何
                                // 视差档位下平移都不会把图推出覆盖区露底。
                                val maxOffset = BackgroundTransformGeometry.maxTranslation(
                                    viewport = viewport,
                                    image = imageSize,
                                    transform = transform,
                                )
                                Image(
                                    bitmap = bitmap,
                                    contentDescription = null,
                                    contentScale = ContentScale.FillBounds,
                                    modifier = Modifier
                                        // requiredSize:完整绘制尺寸超出视口,
                                        // 不受父约束夹回;外层 clipToBounds 收口。
                                        .requiredSize(
                                            width = with(density) { drawnWidth.toDp() },
                                            height = with(density) { drawnHeight.toDp() },
                                        )
                                        .align(Alignment.Center)
                                        .graphicsLayer {
                                            scaleX = depthScale
                                            scaleY = depthScale
                                            translationX = -transform.offsetX * maxOffset.x
                                            translationY = -transform.offsetY * maxOffset.y
                                        }
                                        .alpha(
                                            resolveBackgroundAlpha(
                                                settings.immersionMode,
                                                surfaceRole,
                                            ),
                                        ),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun rememberBackgroundImage(path: String?): ImageBitmap? {
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
    val decoded = BitmapFactory.decodeFile(path, options) ?: return null
    return decoded.uprightByExif(path).asImageBitmap()
}

/**
 * 手机相机照片普遍带 EXIF 方向标记；BitmapFactory 不应用它，直接渲染会横向 /
 * 倒置，且 [BackgroundTransformGeometry] 的 cover 换算会拿到错误宽高比。解码后
 * 统一按 EXIF 转正——renderer 与编辑器共用同一 decode，cover 尺寸语义一致。
 * 采样率按 EXIF 前最长边计算即可，90°/270° 旋转不改变最长边。
 */
private fun Bitmap.uprightByExif(path: String): Bitmap {
    val orientation = runCatching {
        ExifInterface(path).getAttributeInt(
            ExifInterface.TAG_ORIENTATION,
            ExifInterface.ORIENTATION_NORMAL,
        )
    }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)
    val matrix = Matrix()
    when (orientation) {
        ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.setScale(-1f, 1f)
        ExifInterface.ORIENTATION_ROTATE_180 -> matrix.setRotate(180f)
        ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.setScale(1f, -1f)
        ExifInterface.ORIENTATION_TRANSPOSE -> {
            matrix.setRotate(90f)
            matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_ROTATE_90 -> matrix.setRotate(90f)
        ExifInterface.ORIENTATION_TRANSVERSE -> {
            matrix.setRotate(270f)
            matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_ROTATE_270 -> matrix.setRotate(270f)
        else -> return this
    }
    return runCatching {
        Bitmap.createBitmap(this, 0, 0, width, height, matrix, true)
    }.getOrDefault(this)
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

/**
 * 用户照片的亮度与内容不可预知（白底截图、夜景、带字图片都可能）：自定义图
 * 的 scrim 下限必须远高于内置渐变——内置渐变是为可读性调过的受控素材，照片不是。
 * 真实反例：midnight + 白色带字测试图，旧 scrim 0.30 让壁纸文字与正文互相干扰。
 *
 * 取值锚点（Balanced、白图）：midnight 0.74 → 白贡献 ≈ 0.62×0.26 ≈ 16% 灰，
 * 浅文对比充裕；paper 0.42 → 深文可读且照片可辨。上限 0.85 < 1：照片仍然在场，
 * 不盖回不透明，也不退化成「只能选清淡图」。三档保持 氛围<平衡<专注 的次序。
 */
fun resolveCustomImageScrimAlpha(
    mode: ImmersionMode,
    role: SurfaceRole,
    darkBackground: Boolean,
): Float {
    val base = when (mode) {
        ImmersionMode.Atmosphere -> if (darkBackground) 0.62f else 0.30f
        ImmersionMode.Balanced -> if (darkBackground) 0.74f else 0.42f
        ImmersionMode.Focus -> if (darkBackground) 0.82f else 0.54f
    }
    return (base + scrimRoleExtra(role)).coerceIn(0.25f, 0.85f)
}

fun resolveCardContainerAlpha(
    mode: ImmersionMode,
    role: SurfaceRole,
): Float {
    return when (role) {
        SurfaceRole.Today -> when (mode) {
            ImmersionMode.Atmosphere -> 0.78f
            ImmersionMode.Balanced -> 0.86f
            ImmersionMode.Focus -> 0.94f
        }
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
            // 全局背景批:Atmosphere/Balanced 适度透出背景;Focus 保持近实心护表单。
            ImmersionMode.Atmosphere -> 0.84f
            ImmersionMode.Balanced -> 0.89f
            ImmersionMode.Focus -> 0.98f
        }
        SurfaceRole.Edit,
        SurfaceRole.Settings,
        SurfaceRole.Auth -> when (mode) {
            ImmersionMode.Atmosphere -> 0.84f
            ImmersionMode.Balanced -> 0.88f
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
    val isDarkBackground = skin == AppSkin.Midnight
    val scrimAlpha = if (backgroundVisible) {
        if (settings.source == BackgroundSource.CustomImage) {
            // 用户照片走更高下限的专属 scrim（见 resolveCustomImageScrimAlpha），
            // 内置渐变仍用受控素材的旧曲线。
            resolveCustomImageScrimAlpha(settings.immersionMode, role, isDarkBackground)
        } else {
            resolveScrimAlpha(settings.immersionMode, role)
        }
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
