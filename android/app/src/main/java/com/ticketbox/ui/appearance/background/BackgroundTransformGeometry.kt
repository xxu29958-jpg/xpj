package com.ticketbox.ui.appearance.background

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.unit.IntSize
import com.ticketbox.domain.model.BackgroundTransform
import kotlin.math.max

/**
 * 背景 transform 几何换算单源：renderer（graphicsLayer）与编辑器（手势 / 按钮）
 * 共用，任何一端都不许各自猜像素；宽 / 窄屏、不同图比例都由真实视口与图片
 * 尺寸推导。
 *
 * 坐标语义：
 * - cover 基准：图按 [cropBaseScale] 倍放大后恰好填满视口（单一方向可能 bleed）；
 *   renderer 用 requiredSize 把图片层定为完整绘制尺寸（超出视口），外层 clipToBounds；
 * - transform.offsetX / offsetY ∈ [-1, 1] 是「可平移余量」的归一化比例，0 = 居中；
 *   实际平移 translation = -offset × maxTranslation（图片位移与视口视线反向）。
 */
object BackgroundTransformGeometry {
    const val MIN_SCALE = 1f
    const val MAX_SCALE = 3f
    const val OFFSET_LIMIT = 1f

    /** 按钮微调的 offset 归一化步进（可移动余量的比例，与像素无关）。 */
    const val OFFSET_STEP = 0.08f

    /** 缩放按钮倍率。 */
    const val ZOOM_STEP = 1.12f

    fun cropBaseScale(viewport: IntSize, image: IntSize): Float {
        if (viewport.width <= 0 || viewport.height <= 0 || image.width <= 0 || image.height <= 0) return 1f
        return max(
            viewport.width.toFloat() / image.width,
            viewport.height.toFloat() / image.height,
        )
    }

    /** 当前 transform 下单方向的最大平移余量（px）。 */
    fun maxTranslation(
        viewport: IntSize,
        image: IntSize,
        transform: BackgroundTransform,
    ): Offset {
        val base = cropBaseScale(viewport, image)
        val total = base * transform.scale
        val drawnWidth = image.width * total
        val drawnHeight = image.height * total
        return Offset(
            x = max(0f, (drawnWidth - viewport.width) / 2f),
            y = max(0f, (drawnHeight - viewport.height) / 2f),
        )
    }

    /** 拖动手势：pan px 换算成 offset 增量并收敛边界。 */
    fun panned(
        current: BackgroundTransform,
        panPx: Offset,
        viewport: IntSize,
        image: IntSize,
    ): BackgroundTransform {
        val maxOffset = maxTranslation(viewport, image, current)
        val deltaX = if (maxOffset.x > 0f) -panPx.x / maxOffset.x else 0f
        val deltaY = if (maxOffset.y > 0f) -panPx.y / maxOffset.y else 0f
        return clamped(
            current.copy(
                offsetX = current.offsetX + deltaX,
                offsetY = current.offsetY + deltaY,
            ),
        )
    }

    fun zoomed(current: BackgroundTransform, zoomFactor: Float): BackgroundTransform =
        clamped(current.copy(scale = current.scale * zoomFactor))

    fun nudged(current: BackgroundTransform, deltaX: Float, deltaY: Float): BackgroundTransform =
        clamped(
            current.copy(
                offsetX = current.offsetX + deltaX,
                offsetY = current.offsetY + deltaY,
            ),
        )

    fun clamped(transform: BackgroundTransform): BackgroundTransform = transform.copy(
        scale = transform.scale.coerceIn(MIN_SCALE, MAX_SCALE),
        offsetX = transform.offsetX.coerceIn(-OFFSET_LIMIT, OFFSET_LIMIT),
        offsetY = transform.offsetY.coerceIn(-OFFSET_LIMIT, OFFSET_LIMIT),
    )
}
