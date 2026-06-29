package com.ticketbox.ui.mascot

import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.withTransform

private const val V4_VIEWBOX = 520f

/**
 * 夹夹 V4 front pose 的原生矢量渲染:圆角枕形身体(上宽下窄)、顶部两个有洞的纸夹手柄
 * 环、肚前小票 + 红夹口、五官、脚与状态道具。几何来自 docs/design_reference 的
 * final-reference-lock 定稿(见 MASCOT_BRIEF §1-§7),所有颜色取自 [MascotPalette]
 * 语义槽位,三主题自动换色。
 */
internal fun DrawScope.drawJiajiaV4Vector(
    state: MascotState,
    palette: MascotPalette,
    breath: Float,
    zzzPhase: Float,
    actionPhase: Float,
) {
    val scale = minOf(size.width, size.height) / V4_VIEWBOX
    val left = (size.width - V4_VIEWBOX * scale) / 2f
    val top = (size.height - V4_VIEWBOX * scale) / 2f
    val pose = v4Pose(state, breath, actionPhase)
    withTransform(
        {
            translate(left, top)
            scale(scale, scale)
        },
    ) {
        drawV4Shadow(palette, pose)
        withTransform(
            {
                translate(pose.offsetX, pose.offsetY)
                rotate(pose.rotation, pivot = Offset(262f, 292f))
                scale(pose.scaleX, pose.scaleY, pivot = Offset(262f, 292f))
            },
        ) {
            drawV4Feet(palette, pose)
            drawV4TopWires(state, palette, breath, actionPhase)
            drawV4Body(palette)
            drawV4Receipt(state, palette, actionPhase)
            drawV4Clip(state, palette, actionPhase)
            drawV4Face(state, palette)
            drawV4Props(state, palette, actionPhase)
        }
    }
    if (state == MascotState.Dozing) {
        withTransform(
            {
                translate(left, top)
                scale(scale, scale)
            },
        ) {
            drawV4Zzz(palette, zzzPhase)
        }
    }
}

private fun DrawScope.drawV4Shadow(palette: MascotPalette, pose: V4Pose) {
    withTransform({ scale(pose.shadowScale, 1f, pivot = Offset(256f, 496f)) }) {
        drawOval(
            color = palette.outline.copy(alpha = pose.shadowAlpha),
            topLeft = Offset(72f, 476f),
            size = Size(368f, 39f),
        )
    }
}

private fun DrawScope.drawV4Feet(palette: MascotPalette, pose: V4Pose) {
    drawV4Foot(172f, palette, pose.footLift)
    drawV4Foot(352f, palette, pose.footLift)
}

private fun DrawScope.drawV4Foot(centerX: Float, palette: MascotPalette, lift: Float) {
    val topLeft = Offset(centerX - 31f, 434f - lift)
    val footSize = Size(62f, 40f)
    drawOval(palette.bodyFill, topLeft, footSize)
    drawOval(palette.outline, topLeft, footSize, style = Stroke(width = 7f))
    drawOval(palette.bodyHighlight.copy(alpha = 0.4f), Offset(centerX - 18f, 440f - lift), Size(36f, 12f))
}

private fun DrawScope.drawV4TopWires(
    state: MascotState,
    palette: MascotPalette,
    breath: Float,
    phase: Float,
) {
    val arm = v4ArmPose(state, breath, phase)
    drawV4Loop(184f, arm.leftAngle, arm.leftLift, palette, arm.stretchY)
    drawV4Loop(340f, arm.rightAngle, arm.rightLift, palette, arm.stretchY)
}

private fun DrawScope.drawV4Loop(
    centerX: Float,
    angle: Float,
    lift: Float,
    palette: MascotPalette,
    stretchY: Float = 1f,
) {
    withTransform(
        {
            rotate(angle, pivot = Offset(centerX, 180f + lift))
            scale(1f, stretchY, pivot = Offset(centerX, 160f + lift))
        },
    ) {
        val loop = v4Path {
            moveTo(centerX - 18f, 160f + lift)
            cubicTo(centerX - 18f, 140f + lift, centerX - 22f, 132f + lift, centerX - 36f, 118f + lift)
            cubicTo(centerX - 60f, 94f + lift, centerX - 50f, 52f + lift, centerX - 22f, 38f + lift)
            cubicTo(centerX + 10f, 22f + lift, centerX + 44f, 42f + lift, centerX + 42f, 76f + lift)
            cubicTo(centerX + 41f, 100f + lift, centerX + 18f, 116f + lift, centerX + 16f, 160f + lift)
        }
        drawPath(
            loop,
            color = palette.outline,
            style = Stroke(width = 11f, cap = StrokeCap.Round, join = StrokeJoin.Round),
        )
        drawPath(
            loop,
            color = palette.bodyHighlight.copy(alpha = 0.96f),
            style = Stroke(width = 5.5f, cap = StrokeCap.Round, join = StrokeJoin.Round),
        )
        drawPath(
            loop,
            color = palette.wireStroke.copy(alpha = 0.5f),
            style = Stroke(width = 2.5f, cap = StrokeCap.Round, join = StrokeJoin.Round),
        )
    }
}

private fun DrawScope.drawV4Body(palette: MascotPalette) {
    drawFilledStrokePath(
        v4Path {
            moveTo(150f, 164f)
            lineTo(374f, 164f)
            quadraticTo(420f, 164f, 430f, 206f)
            cubicTo(452f, 278f, 446f, 372f, 418f, 420f)
            quadraticTo(404f, 444f, 356f, 444f)
            lineTo(168f, 444f)
            quadraticTo(120f, 444f, 106f, 420f)
            cubicTo(78f, 372f, 72f, 278f, 94f, 206f)
            quadraticTo(104f, 164f, 150f, 164f)
            close()
        },
        fill = palette.bodyFill,
        stroke = palette.outline,
    )
    drawPath(
        v4Path {
            moveTo(126f, 181f)
            quadraticTo(146f, 166f, 206f, 166f)
            lineTo(318f, 166f)
            quadraticTo(374f, 166f, 398f, 184f)
            quadraticTo(338f, 214f, 262f, 216f)
            quadraticTo(186f, 216f, 126f, 193f)
            close()
        },
        color = palette.bodyHighlight.copy(alpha = 0.22f),
    )
    drawOval(
        color = palette.bodyHighlight.copy(alpha = 0.55f),
        topLeft = Offset(126f, 166f),
        size = Size(28f, 16f),
    )
}

private fun DrawScope.drawV4Receipt(state: MascotState, palette: MascotPalette, phase: Float) {
    val paper = v4ReceiptMotion(state, phase)
    withTransform(
        {
            translate(0f, paper.offsetY)
            rotate(paper.rotation, pivot = Offset(262f, 370f))
        },
    ) {
        drawFilledStrokePath(
            v4Path {
                moveTo(198f, 368f)
                lineTo(326f, 368f)
                lineTo(326f, 486f)
                quadraticTo(321f, 494f, 316f, 488f)
                quadraticTo(311f, 482f, 306f, 488f)
                quadraticTo(301f, 494f, 296f, 488f)
                quadraticTo(291f, 482f, 286f, 488f)
                quadraticTo(281f, 494f, 276f, 488f)
                quadraticTo(271f, 482f, 266f, 488f)
                quadraticTo(261f, 494f, 256f, 488f)
                quadraticTo(251f, 482f, 246f, 488f)
                quadraticTo(241f, 494f, 236f, 488f)
                quadraticTo(231f, 482f, 226f, 488f)
                quadraticTo(221f, 494f, 216f, 488f)
                quadraticTo(207f, 484f, 198f, 488f)
                close()
            },
            fill = palette.receiptFill,
            stroke = palette.outline,
            strokeWidth = 5.4f,
        )
        listOf(406f, 434f, 460f).forEachIndexed { index, y ->
            drawLine(
                color = palette.receiptRule.copy(alpha = if (index == 2) 0.82f else 1f),
                start = Offset(226f, y),
                end = Offset(if (index == 2) 294f else 306f, y),
                strokeWidth = 4.2f,
                cap = StrokeCap.Round,
            )
        }
    }
}

private fun DrawScope.drawV4Clip(state: MascotState, palette: MascotPalette, phase: Float) {
    val paper = v4ReceiptMotion(state, phase)
    withTransform(
        {
            translate(0f, paper.offsetY)
            rotate(paper.rotation, pivot = Offset(262f, 370f))
        },
    ) {
        drawFilledStrokePath(
            v4Path {
                moveTo(243f, 350f)
                lineTo(281f, 350f)
                quadraticTo(287f, 350f, 287f, 356f)
                lineTo(287f, 377f)
                quadraticTo(284f, 386f, 276f, 386f)
                lineTo(270f, 386f)
                lineTo(270f, 372f)
                lineTo(263f, 372f)
                lineTo(263f, 386f)
                lineTo(251f, 386f)
                quadraticTo(239f, 386f, 239f, 377f)
                lineTo(239f, 356f)
                quadraticTo(239f, 350f, 243f, 350f)
                close()
            },
            fill = palette.clipAccent,
            stroke = palette.outline,
            strokeWidth = 5.6f,
        )
        drawRoundRect(
            color = palette.bodyHighlight.copy(alpha = 0.30f),
            topLeft = Offset(247f, 357f),
            size = Size(30f, 9f),
            cornerRadius = CornerRadius(5f, 5f),
        )
        drawLine(palette.outline.copy(alpha = 0.36f), Offset(255f, 354f), Offset(255f, 377f), 3.5f, StrokeCap.Round)
        drawLine(palette.outline.copy(alpha = 0.36f), Offset(269f, 354f), Offset(269f, 377f), 3.5f, StrokeCap.Round)
    }
}
