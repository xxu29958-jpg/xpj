package com.ticketbox.ui.mascot

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke

internal fun DrawScope.drawFilledStrokePath(
    path: Path,
    fill: Color,
    stroke: Color,
    strokeWidth: Float = 7f,
) {
    drawPath(path, color = fill)
    drawPath(
        path = path,
        color = stroke,
        style = Stroke(width = strokeWidth, cap = StrokeCap.Round, join = StrokeJoin.Round),
    )
}

internal fun v4Path(build: Path.() -> Unit): Path = Path().apply(build)
