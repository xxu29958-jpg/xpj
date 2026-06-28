package com.ticketbox.ui.mascot

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke

private const val LEFT_EYE_X = 198f
private const val RIGHT_EYE_X = 326f
private const val EYE_Y = 286f

internal fun DrawScope.drawV4Face(state: MascotState, palette: MascotPalette) {
    when (state) {
        MascotState.Dozing -> {
            drawV4ClosedEye(LEFT_EYE_X, palette, sleepy = true)
            drawV4ClosedEye(RIGHT_EYE_X, palette, sleepy = true)
        }
        MascotState.ClampCheer,
        MascotState.Celebrating,
        MascotState.Tickled,
        -> {
            drawV4ClosedEye(LEFT_EYE_X, palette, sleepy = false)
            drawV4ClosedEye(RIGHT_EYE_X, palette, sleepy = false)
        }
        MascotState.Shocked -> {
            drawV4OpenEye(LEFT_EYE_X, palette, rx = 25.5f, ry = 29f)
            drawV4OpenEye(RIGHT_EYE_X, palette, rx = 25.5f, ry = 29f)
        }
        MascotState.Dismissive -> {
            drawCircle(palette.outline, radius = 17f, center = Offset(LEFT_EYE_X - 6f, EYE_Y))
            drawCircle(palette.outline, radius = 17f, center = Offset(RIGHT_EYE_X - 6f, EYE_Y))
        }
        else -> {
            drawV4OpenEye(LEFT_EYE_X, palette)
            drawV4OpenEye(RIGHT_EYE_X, palette)
        }
    }
    drawOval(palette.blushFill.copy(alpha = 0.94f), Offset(126f, 312f), Size(50f, 30f))
    drawOval(palette.blushFill.copy(alpha = 0.94f), Offset(348f, 312f), Size(50f, 30f))
    drawV4Mouth(state, palette)
}

private fun DrawScope.drawV4OpenEye(cx: Float, palette: MascotPalette, rx: Float = 24f, ry: Float = 27.5f) {
    drawOval(palette.outline, topLeft = Offset(cx - rx, EYE_Y - ry), size = Size(rx * 2f, ry * 2f))
    drawCircle(palette.receiptFill, radius = rx * 0.38f, center = Offset(cx - rx * 0.36f, EYE_Y - ry * 0.42f))
    drawCircle(palette.receiptFill.copy(alpha = 0.92f), radius = rx * 0.18f, center = Offset(cx + rx * 0.30f, EYE_Y + ry * 0.34f))
    drawCircle(palette.receiptFill.copy(alpha = 0.76f), radius = rx * 0.10f, center = Offset(cx + rx * 0.05f, EYE_Y - ry * 0.12f))
}

private fun DrawScope.drawV4ClosedEye(x: Float, palette: MascotPalette, sleepy: Boolean) {
    val controlY = if (sleepy) EYE_Y + 17f else EYE_Y - 20f
    drawPath(
        v4Path {
            moveTo(x - 20f, EYE_Y)
            quadraticTo(x, controlY, x + 20f, EYE_Y)
        },
        color = palette.outline,
        style = Stroke(width = 5f, cap = StrokeCap.Round, join = StrokeJoin.Round),
    )
}

private fun DrawScope.drawV4Mouth(state: MascotState, palette: MascotPalette) {
    when (state) {
        MascotState.Shocked -> drawOval(
            color = palette.clipAccent,
            topLeft = Offset(253f, 310f),
            size = Size(18f, 24f),
            style = Stroke(width = 4.5f, cap = StrokeCap.Round),
        )
        MascotState.Dismissive -> drawLine(palette.clipAccent, Offset(246f, 322f), Offset(278f, 319f), 4.8f, StrokeCap.Round)
        else -> drawPath(
            v4Path {
                moveTo(244f, 322f)
                quadraticTo(253f, 332f, 262f, 322f)
                quadraticTo(271f, 332f, 280f, 322f)
            },
            color = palette.clipAccent,
            style = Stroke(width = 5.4f, cap = StrokeCap.Round, join = StrokeJoin.Round),
        )
    }
}
