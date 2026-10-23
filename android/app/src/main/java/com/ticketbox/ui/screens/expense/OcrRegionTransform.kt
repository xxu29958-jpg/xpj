package com.ticketbox.ui.screens.expense

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
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
