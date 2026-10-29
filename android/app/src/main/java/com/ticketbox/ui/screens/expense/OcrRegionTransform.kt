package com.ticketbox.ui.screens.expense

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import com.ticketbox.domain.model.RecognitionSourceLocation
import kotlin.math.min

internal data class OcrRegionTransform(val zoom: Float = 1f, val pan: Offset = Offset.Zero) {
    fun scale(viewport: Size, source: Size): Float =
        min(viewport.width / source.width, viewport.height / source.height) * zoom

    fun margin(viewport: Size, source: Size): Offset {
        val scale = scale(viewport, source)
        return Offset((viewport.width - source.width * scale) / 2, (viewport.height - source.height * scale) / 2) + pan
    }

    fun sourcePoint(point: Offset, viewport: Size, source: Size): Offset {
        val scale = scale(viewport, source)
        val relative = (point - margin(viewport, source)) / scale
        return Offset(relative.x.coerceIn(0f, source.width), relative.y.coerceIn(0f, source.height))
    }

    fun adjusted(factor: Float, delta: Offset, centroid: Offset, viewport: Size, source: Size): OcrRegionTransform {
        val nextZoom = (zoom * factor).coerceIn(1f, 16f)
        val center = Offset(viewport.width / 2, viewport.height / 2)
        val nextPan = (pan + center - centroid) * (nextZoom / zoom) + centroid - center + delta
        val next = copy(zoom = nextZoom)
        val scale = next.scale(viewport, source)
        val xLimit = ((source.width * scale - viewport.width) / 2).coerceAtLeast(0f)
        val yLimit = ((source.height * scale - viewport.height) / 2).coerceAtLeast(0f)
        return next.copy(pan = Offset(nextPan.x.coerceIn(-xLimit, xLimit), nextPan.y.coerceIn(-yLimit, yLimit)))
    }
}

internal fun focusSourceLocation(location: RecognitionSourceLocation, viewport: Size): OcrRegionTransform {
    val source = Size(location.width.toFloat(), location.height.toFloat())
    val points = location.boxes.flatten()
    val left = points.minOf { it[0] }; val right = points.maxOf { it[0] }
    val top = points.minOf { it[1] }; val bottom = points.maxOf { it[1] }
    val base = OcrRegionTransform().scale(viewport, source)
    val zoom = (minOf(viewport.width / (right - left).coerceAtLeast(1f),
        viewport.height / (bottom - top).coerceAtLeast(1f)) * .8f / base).coerceIn(1f, 16f)
    val pan = Offset((source.width - left - right) / 2, (source.height - top - bottom) / 2) * (base * zoom)
    return OcrRegionTransform(zoom, pan).adjusted(1f, Offset.Zero, Offset.Zero, viewport, source)
}
