package com.ticketbox.ui.appearance.background

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import com.ticketbox.domain.model.BackgroundTransform
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.design.themeVisualsForSkin
import java.io.File

/**
 * What the shell needs to know about the canvas: whether a measured photo is drawn, its immersion,
 * and how tall the shell header is. The header only carries a large title, so it is veiled to the
 * large-text target and becomes the place where the photo is plainly visible.
 */
@Stable
class CanvasPhotoState internal constructor() {
    /** The photo the canvas is drawing right now; it lags a new choice until that photo has decoded. */
    var photoPath by mutableStateOf<String?>(null)
        internal set
    /**
     * A photo is configured and has not failed to decode. Geometry that opens onto the photo (the
     * root header's window) follows this, so it is laid out once instead of shifting when decoding ends.
     */
    var photoWindow by mutableStateOf(false)
        internal set
    var immersion by mutableStateOf(ImmersionMode.Balanced)
        internal set

    /** Height in px of the shell header band (status bar included); 0 while no header shows. */
    var headerBandPx by mutableIntStateOf(0)
}

val LocalCanvasPhotoState = staticCompositionLocalOf<CanvasPhotoState?> { null }

/**
 * The one background canvas. A user photo is drawn at full strength and veiled only as much as
 * its own pixels require for the text the page leaves on the canvas; immersion and page role then
 * add calm on top of that floor. Controlled built-in artwork keeps its tuned curve.
 */
/** What the page leaves on the canvas: the demand below the header, and the header band height. */
internal data class CanvasLayout(val canvasText: CanvasTextDemand = CanvasTextDemand.Body, val headerBandPx: Int = 0)

@Composable
internal fun BackgroundCanvas(
    settings: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
    photo: DecodedBackground?,
    layout: CanvasLayout = CanvasLayout(),
) {
    // One parallax depth drives both the photo layer and the veil's sampling frame.
    val depthScale by rememberParallaxDepth(settings, role)
    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val viewport = IntSize(constraints.maxWidth, constraints.maxHeight)
        TicketboxBackgroundLayer(settings = settings, skin = skin, surfaceRole = role, photo = photo, depthScale = { depthScale })
        if (photo == null) {
            Box(Modifier.fillMaxSize().background(resolveGlobalScrim(settings, skin, role)))
            BottomReadabilityScrim(settings = settings, skin = skin, role = role)
        } else {
            PhotoVeil(settings, skin, role, PhotoVeilInputs(photo, viewport, layout.canvasText, layout.headerBandPx, depthScale))
        }
    }
}

private class PhotoVeilInputs(
    val photo: DecodedBackground,
    val viewport: IntSize,
    val canvasText: CanvasTextDemand,
    headerBandPx: Int,
    val depthScale: Float,
) {
    val header = headerBandPx.coerceIn(0, viewport.height)
}

@Composable
private fun BoxScope.PhotoVeil(settings: BackgroundSettings, skin: AppSkin, role: SurfaceRole, inputs: PhotoVeilInputs) {
    val photo = inputs.photo
    val viewport = inputs.viewport
    val transform = settings.transform
    val navigationPx = with(LocalDensity.current) { PhotoNavigationScrimHeight.roundToPx() }
    val headerRampPx = with(LocalDensity.current) { HeaderRampMax.toPx() }
    val needs = remember(photo, skin, inputs.canvasText, viewport, transform, inputs.header, navigationPx, inputs.depthScale) {
        val header = inputs.header
        val frame = PhotoFrame(photo.size, viewport, transform, inputs.depthScale)
        fun need(demand: CanvasTextDemand, rows: IntRange) =
            BackgroundReadability.regionNeed(photo.needs(skin, demand), photo.profile, frame, rows)
        val edges = (0..BackgroundReadability.BAND_COUNT).map { header + (viewport.height - header) * it / BackgroundReadability.BAND_COUNT }
        Triple(
            if (header == 0) 0f else need(CanvasTextDemand.Display, 0 until header),
            List(BackgroundReadability.BAND_COUNT) { need(inputs.canvasText, edges[it] until edges[it + 1]) },
            need(CanvasTextDemand.Body, (viewport.height - navigationPx).coerceAtLeast(0) until viewport.height),
        )
    }
    val (headerNeed, bodyNeeds, navigationNeed) = needs
    val veil = canvasVeilColor(skin)
    val dark = skin == AppSkin.Midnight
    Box(
        Modifier.fillMaxSize().background(
            veilBrush(
                color = veil,
                headerAlpha = photoVeilAlpha(headerNeed, settings.immersionMode, role, dark),
                headerFraction = inputs.header / viewport.height.coerceAtLeast(1).toFloat(),
                rampFraction = minOf(inputs.header * HeaderRampShare, headerRampPx) / viewport.height.coerceAtLeast(1).toFloat(),
                bands = bodyNeeds.map { photoVeilAlpha(it, settings.immersionMode, role, dark) },
            ),
        ),
    )
    Box(
        modifier = Modifier
            .align(Alignment.BottomCenter)
            .fillMaxWidth()
            .height(PhotoNavigationScrimHeight)
            .background(
                Brush.verticalGradient(
                    0f to Color.Transparent,
                    0.45f to veil.copy(alpha = navigationNeed),
                    1f to veil.copy(alpha = navigationNeed),
                ),
            ),
    )
}

private val PhotoNavigationScrimHeight = 176.dp

internal fun customPhotoPath(settings: BackgroundSettings): String? =
    settings.customImagePath?.takeIf { settings.source == BackgroundSource.CustomImage && File(it).isFile }

/** Veil tone: the skin's own canvas colour, so a veiled photo still reads as paper or midnight. */
internal fun canvasVeilColor(skin: AppSkin): Color = themeVisualsForSkin(skin).backgroundTop

/** Contrast target for the text a page leaves on the canvas, in the skin's real text colours. */
internal fun canvasTextTarget(skin: AppSkin, demand: CanvasTextDemand): CanvasTextTarget {
    val visuals = themeVisualsForSkin(skin)
    return when (demand) {
        // Meta text and primary-coloured links are the faintest small text left on the canvas.
        CanvasTextDemand.Body -> CanvasTextTarget(texts = listOf(visuals.textMeta, visuals.primary), ratio = 4.5f)
        // The shell title is primary-coloured; default text covers any other large title.
        CanvasTextDemand.Display -> CanvasTextTarget(texts = listOf(visuals.textDefault, visuals.primary), ratio = 3f)
    }
}

/**
 * Final photo veil: never below the measured [need]; immersion sets a floor and calm, and
 * editing or settings pages add restraint. Everything composites, so the result only grows.
 */
fun photoVeilAlpha(need: Float, mode: ImmersionMode, role: SurfaceRole, dark: Boolean): Float {
    val floor = when (mode) {
        ImmersionMode.Atmosphere -> if (dark) 0.14f else 0.08f
        ImmersionMode.Balanced -> if (dark) 0.30f else 0.24f
        ImmersionMode.Focus -> if (dark) 0.52f else 0.46f
    }
    val calm = when (mode) {
        ImmersionMode.Atmosphere -> 0f
        ImmersionMode.Balanced -> 0.20f
        ImmersionMode.Focus -> 0.45f
    }
    val restraint = when (role) {
        SurfaceRole.Today, SurfaceRole.Pending, SurfaceRole.Stats -> 0f
        SurfaceRole.Ledger -> 0.06f
        SurfaceRole.Auth -> 0.16f
        SurfaceRole.Edit, SurfaceRole.Settings -> 0.22f
    }
    return 1f - (1f - maxOf(need, floor)) * (1f - calm) * (1f - restraint)
}

/**
 * The header band keeps its own (large-title) veil; below it, band alphas become one gradient.
 * Every boundary takes the larger neighbour, so interpolation never drops a region below its need.
 * The header softens into the content inside its own bottom edge, where the veil only grows.
 */
private fun veilBrush(color: Color, headerAlpha: Float, headerFraction: Float, rampFraction: Float, bands: List<Float>): Brush {
    val count = bands.size
    val span = 1f - headerFraction
    val stops = buildList {
        if (headerFraction > 0f) {
            add(0f to color.copy(alpha = headerAlpha))
            add((headerFraction - rampFraction).coerceAtLeast(0f) to color.copy(alpha = headerAlpha))
        }
        add(headerFraction to color.copy(alpha = maxOf(bands.first(), if (headerFraction > 0f) headerAlpha else 0f)))
        bands.forEachIndexed { index, alpha ->
            add(headerFraction + span * (index + 0.5f) / count to color.copy(alpha = alpha))
            if (index < count - 1) add(headerFraction + span * (index + 1f) / count to color.copy(alpha = maxOf(alpha, bands[index + 1])))
        }
        add(1f to color.copy(alpha = bands.last()))
    }
    return Brush.verticalGradient(*stops.toTypedArray())
}

/** The softening ramp takes at most this share of the header, below the title row. */
private const val HeaderRampShare = 0.35f
private val HeaderRampMax = 48.dp

/**
 * 自由构图渲染：Image 层尺寸 = 完整绘制尺寸（超出视口），外层 clipToBounds；平移在视口内
 * 移动 oversized 层，露出的是原图其余部分。不能用 ContentScale.Crop + graphicsLayer 平移已
 * 裁到视口的层——那只会露底。照片满强度绘制，可读性只由按图实测的遮罩负责。
 */
@Composable
internal fun PhotoLayer(photo: DecodedBackground, transform: BackgroundTransform, depthScale: () -> Float) {
    BoxWithConstraints(modifier = Modifier.fillMaxSize().clipToBounds()) {
        val viewport = IntSize(constraints.maxWidth, constraints.maxHeight)
        val density = LocalDensity.current
        val coverScale = BackgroundTransformGeometry.cropBaseScale(viewport = viewport, image = photo.size)
        // 视差 depthScale 只放大层、不纳入平移余量：任何视差档位下平移都不会把图推出覆盖区露底。
        val maxOffset = BackgroundTransformGeometry.maxTranslation(viewport = viewport, image = photo.size, transform = transform)
        Image(
            bitmap = photo.image,
            contentDescription = null,
            contentScale = ContentScale.FillBounds,
            modifier = Modifier
                // requiredSize：完整绘制尺寸超出视口，不受父约束夹回；外层 clipToBounds 收口。
                .requiredSize(
                    width = with(density) { (photo.size.width * coverScale * transform.scale).toDp() },
                    height = with(density) { (photo.size.height * coverScale * transform.scale).toDp() },
                )
                .align(Alignment.Center)
                .graphicsLayer {
                    scaleX = depthScale()
                    scaleY = depthScale()
                    translationX = -transform.offsetX * maxOffset.x
                    translationY = -transform.offsetY * maxOffset.y
                },
        )
    }
}

internal fun CanvasPhotoState.publish(photo: BackgroundPhoto, mode: ImmersionMode) {
    photoPath = photo.photo?.path
    photoWindow = photo.reservesWindow
    immersion = mode
}

/** The parallax zoom for a page role; reduce motion and a disabled parallax keep the photo at its own scale. */
@Composable
internal fun rememberParallaxDepth(settings: BackgroundSettings, role: SurfaceRole): State<Float> = animateFloatAsState(
    targetValue = if (settings.enableParallax && !settings.reduceMotion) parallaxDepthScale(role) else 1f,
    animationSpec = tween(durationMillis = if (settings.reduceMotion) 0 else 220),
    label = "backgroundDepthScale",
)

private fun parallaxDepthScale(role: SurfaceRole): Float = when (role) {
    SurfaceRole.Today -> 1.04f
    SurfaceRole.Pending -> 1.05f
    SurfaceRole.Stats -> 1.045f
    SurfaceRole.Ledger -> 1.015f
    SurfaceRole.Edit -> 1.015f
    SurfaceRole.Settings -> 1.01f
    SurfaceRole.Auth -> 1.02f
}
