package com.ticketbox.ui.mascot

import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate

internal fun DrawScope.drawV4Props(state: MascotState, palette: MascotPalette, phase: Float) {
    when (state) {
        MascotState.Greeting -> drawV4WaveMarks(palette, phase)
        MascotState.ClampCheer -> drawV4Hearts(palette, phase)
        MascotState.Celebrating -> drawV4Confetti(palette, phase)
        MascotState.Juggling -> drawV4Coin(palette, phase)
        MascotState.Searching -> drawV4Magnifier(palette)
        MascotState.Shocked -> drawV4SweatDrop(palette)
        MascotState.Stretching -> {
            drawLine(palette.wireStroke.copy(alpha = 0.55f), Offset(156f, 44f), Offset(150f, 22f), 4f, StrokeCap.Round)
            drawLine(palette.wireStroke.copy(alpha = 0.55f), Offset(368f, 44f), Offset(374f, 22f), 4f, StrokeCap.Round)
        }
        MascotState.Tickled -> {
            drawLine(palette.clipAccent.copy(alpha = 0.65f), Offset(112f, 286f), Offset(92f, 266f), 5f, StrokeCap.Round)
            drawLine(palette.clipAccent.copy(alpha = 0.65f), Offset(408f, 286f), Offset(428f, 266f), 5f, StrokeCap.Round)
        }
        MascotState.Dismissive -> drawLine(palette.wireStroke.copy(alpha = 0.62f), Offset(402f, 246f), Offset(442f, 228f), 5f, StrokeCap.Round)
        else -> Unit
    }
}

internal fun DrawScope.drawV4Zzz(palette: MascotPalette, phase: Float) {
    repeat(3) { index ->
        val p = (phase + index * 0.28f) % 1f
        val x = 78f + index * 30f + p * 16f
        val y = 150f - index * 32f - p * 22f
        val size = 40f - index * 7f
        drawZGlyph(palette.propInfo.copy(alpha = (1f - p) * 0.85f), x, y, size)
    }
}

private fun DrawScope.drawV4WaveMarks(palette: MascotPalette, phase: Float) {
    val dx = (phase - 0.5f) * 8f
    drawArc(
        color = palette.clipAccent.copy(alpha = 0.72f),
        startAngle = 215f,
        sweepAngle = 88f,
        useCenter = false,
        topLeft = Offset(74f + dx, 120f),
        size = Size(56f, 45f),
        style = Stroke(width = 5f, cap = StrokeCap.Round),
    )
    drawArc(
        color = palette.clipAccent.copy(alpha = 0.54f),
        startAngle = 215f,
        sweepAngle = 88f,
        useCenter = false,
        topLeft = Offset(50f + dx, 150f),
        size = Size(44f, 35f),
        style = Stroke(width = 4f, cap = StrokeCap.Round),
    )
}

private fun DrawScope.drawV4Hearts(palette: MascotPalette, phase: Float) {
    drawV4Heart(Offset(92f, 152f - phase * 12f), 28f, palette.clipAccent)
    drawV4Heart(Offset(404f, 150f - phase * 10f), 22f, palette.propSuccess)
}

private fun DrawScope.drawV4Heart(center: Offset, radius: Float, color: Color) {
    drawPath(
        v4Path {
            moveTo(center.x, center.y + radius * 0.62f)
            cubicTo(center.x - radius * 1.30f, center.y - radius * 0.10f, center.x - radius * 0.78f, center.y - radius * 0.94f, center.x, center.y - radius * 0.35f)
            cubicTo(center.x + radius * 0.78f, center.y - radius * 0.94f, center.x + radius * 1.30f, center.y - radius * 0.10f, center.x, center.y + radius * 0.62f)
            close()
        },
        color = color.copy(alpha = 0.88f),
    )
}

private fun DrawScope.drawV4Confetti(palette: MascotPalette, phase: Float) {
    val pieces = listOf(
        V4Confetti(96f, 96f, -18f, palette.propSuccess),
        V4Confetti(150f, 54f, 24f, palette.propWarn),
        V4Confetti(374f, 64f, 18f, palette.propInfo),
        V4Confetti(412f, 110f, -24f, palette.clipAccent),
        V4Confetti(262f, 48f, 10f, palette.clipAccent),
    )
    pieces.forEach { piece ->
        rotate(piece.rotation, Offset(piece.x, piece.y - phase * 12f)) {
            drawRoundRect(
                piece.color.copy(alpha = 0.88f),
                topLeft = Offset(piece.x - 8f, piece.y - phase * 12f - 8f),
                size = Size(16f, 16f),
                cornerRadius = CornerRadius(3f, 3f),
            )
        }
    }
}

private fun DrawScope.drawV4Coin(palette: MascotPalette, phase: Float) {
    val center = Offset(370f + phase * 18f, 150f - phase * 20f)
    drawCircle(palette.propWarn.copy(alpha = 0.92f), 22f, center)
    drawCircle(palette.outline, 22f, center, style = Stroke(width = 4f))
    drawLine(palette.outline.copy(alpha = 0.50f), Offset(center.x - 9f, center.y), Offset(center.x + 9f, center.y), 3f, StrokeCap.Round)
}

private fun DrawScope.drawV4Magnifier(palette: MascotPalette) {
    val center = Offset(404f, 272f)
    drawCircle(palette.receiptFill.copy(alpha = 0.78f), 40f, center)
    drawCircle(palette.propInfo, 40f, center, style = Stroke(width = 8f))
    drawCircle(palette.receiptFill.copy(alpha = 0.70f), 13f, Offset(393f, 257f))
    drawLine(palette.propInfo, Offset(432f, 298f), Offset(476f, 342f), 9f, StrokeCap.Round)
    drawCircle(palette.outline, 9f, Offset(326f, 286f))
}

private fun DrawScope.drawV4SweatDrop(palette: MascotPalette) {
    drawFilledStrokePath(
        v4Path {
            moveTo(400f, 246f)
            cubicTo(428f, 284f, 415f, 314f, 390f, 315f)
            cubicTo(365f, 314f, 358f, 285f, 400f, 246f)
            close()
        },
        fill = palette.propInfo,
        stroke = palette.outline,
        strokeWidth = 4f,
    )
}

private fun DrawScope.drawZGlyph(color: Color, x: Float, y: Float, size: Float) {
    drawPath(
        v4Path {
            moveTo(x, y)
            lineTo(x + size, y)
            lineTo(x + size * 0.10f, y + size)
            lineTo(x + size * 1.05f, y + size)
        },
        color = color,
        style = Stroke(width = 5f, cap = StrokeCap.Round),
    )
}

private data class V4Confetti(
    val x: Float,
    val y: Float,
    val rotation: Float,
    val color: Color,
)
