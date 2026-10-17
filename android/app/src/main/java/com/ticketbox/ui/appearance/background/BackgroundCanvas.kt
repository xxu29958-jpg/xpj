package com.ticketbox.ui.appearance.background

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
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
 * The one background canvas. A user photo is drawn at full strength and veiled only as much as
 * its own pixels require for the text the page leaves on the canvas; immersion and page role then
 * add calm on top of that floor. Controlled built-in artwork keeps its tuned curve.
 */
@Composable
internal fun BackgroundCanvas(
    settings: BackgroundSettings,
    skin: AppSkin,
    role: SurfaceRole,
    canvasText: CanvasTextDemand,
) {
    val photo = rememberBackgroundImage(customPhotoPath(settings))
    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val viewport = IntSize(constraints.maxWidth, constraints.maxHeight)
        TicketboxBackgroundLayer(settings = settings, skin = skin, surfaceRole = role, photo = photo)
        if (photo == null) {
            Box(Modifier.fillMaxSize().background(resolveGlobalScrim(settings, skin, role)))
            BottomReadabilityScrim(settings = settings, skin = skin, role = role)
        } else {
            val transform = settings.transform
            val canvasNeeds = remember(photo, skin, canvasText, viewport, transform) {
                BackgroundReadability.bandNeeds(photo.needs(skin, canvasText), photo.profile, photo.size, viewport, transform)
            }
            val navigationNeed = remember(photo, skin, viewport, transform) {
                BackgroundReadability.bandNeeds(photo.needs(skin, CanvasTextDemand.Body), photo.profile, photo.size, viewport, transform)
                    .last()
            }
            val veil = canvasVeilColor(skin)
            val dark = skin == AppSkin.Midnight
            val alphas = canvasNeeds.map { photoVeilAlpha(it, settings.immersionMode, role, dark) }
            Box(Modifier.fillMaxSize().background(bandedVeil(veil, alphas)))
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
    }
}

private val PhotoNavigationScrimHeight = 176.dp

private fun customPhotoPath(settings: BackgroundSettings): String? =
    settings.customImagePath?.takeIf { settings.source == BackgroundSource.CustomImage && File(it).isFile }

/** Veil tone: the skin's own canvas colour, so a veiled photo still reads as paper or midnight. */
internal fun canvasVeilColor(skin: AppSkin): Color = themeVisualsForSkin(skin).backgroundTop

/** Contrast target for the text a page leaves on the canvas, in the skin's real text colours. */
internal fun canvasTextTarget(skin: AppSkin, demand: CanvasTextDemand): CanvasTextTarget {
    val visuals = themeVisualsForSkin(skin)
    return when (demand) {
        CanvasTextDemand.Body -> CanvasTextTarget(text = visuals.textMeta, ratio = 4.5f)
        CanvasTextDemand.Display -> CanvasTextTarget(text = visuals.textDefault, ratio = 3f)
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
 * Band alphas become one vertical gradient. Each band boundary takes the larger neighbour, so
 * interpolation never drops a band below its own requirement.
 */
private fun bandedVeil(color: Color, alphas: List<Float>): Brush {
    val count = alphas.size
    val stops = buildList {
        add(0f to color.copy(alpha = alphas.first()))
        alphas.forEachIndexed { index, alpha ->
            add((index + 0.5f) / count to color.copy(alpha = alpha))
            if (index < count - 1) add((index + 1f) / count to color.copy(alpha = maxOf(alpha, alphas[index + 1])))
        }
        add(1f to color.copy(alpha = alphas.last()))
    }
    return Brush.verticalGradient(*stops.toTypedArray())
}

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
