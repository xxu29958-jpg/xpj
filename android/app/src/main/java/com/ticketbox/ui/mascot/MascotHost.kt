package com.ticketbox.ui.mascot

import android.os.SystemClock
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

/**
 * 夹夹的 Compose 持有者:把 app 事件喂给 [MascotStateMachine],按节拍推进
 * 过期回落,向 UI 暴露当前 [MascotState]。渲染端无关——占位画布和未来的
 * Rive 绑定(ADR-0048)消费同一个 controller,集成时只换渲染、不动事件接线。
 */
@Stable
class MascotController internal constructor(
    private val machine: MascotStateMachine,
    private val clock: () -> Long,
) {
    var state: MascotState by mutableStateOf(MascotState.Neutral)
        private set

    fun onEvent(event: MascotEvent) {
        state = machine.onEvent(event, clock())
    }

    internal fun tick() {
        state = machine.onTick(clock())
    }
}

/** 记住一个 controller 并启动回落节拍(one-shot 到时回环境态靠它推进)。 */
@Composable
fun rememberMascotController(clock: () -> Long = SystemClock::uptimeMillis): MascotController {
    val controller = remember { MascotController(MascotStateMachine(), clock) }
    LaunchedEffect(controller) {
        while (isActive) {
            delay(MASCOT_TICK_MS)
            controller.tick()
        }
    }
    return controller
}

/**
 * 占位渲染:token 化的极简夹夹剪影(身体/金属丝手臂/眼睛/腮红),让空态接线
 * 可以先行。**这不是定稿视觉**——.riv 出炉后由 Rive 集成 PR 整体替换本画布,
 * 消费面(state + palette)不变。打盹态闭眼,其余睁眼,不再做更多表情分支。
 */
@Composable
fun MascotPlaceholder(
    state: MascotState,
    palette: MascotPalette,
    modifier: Modifier = Modifier,
    size: Dp = 96.dp,
) {
    Canvas(modifier = modifier.size(size)) {
        drawJiajiaPlaceholder(state, palette)
    }
}

private fun DrawScope.drawJiajiaPlaceholder(state: MascotState, palette: MascotPalette) {
    val w = size.width
    val h = size.height
    val stroke = w * 0.035f
    // 金属丝手臂(记忆钩):两条弧线从身体顶部弹出。
    drawArc(
        color = palette.wireStroke,
        startAngle = 180f,
        sweepAngle = 120f,
        useCenter = false,
        topLeft = Offset(w * 0.10f, h * 0.04f),
        size = Size(w * 0.34f, h * 0.30f),
        style = Stroke(width = stroke, cap = StrokeCap.Round),
    )
    drawArc(
        color = palette.wireStroke,
        startAngle = 240f,
        sweepAngle = 120f,
        useCenter = false,
        topLeft = Offset(w * 0.56f, h * 0.04f),
        size = Size(w * 0.34f, h * 0.30f),
        style = Stroke(width = stroke, cap = StrokeCap.Round),
    )
    // 圆胖身体:填充 + 描边。
    val bodyTopLeft = Offset(w * 0.15f, h * 0.24f)
    val bodySize = Size(w * 0.70f, h * 0.60f)
    val corner = CornerRadius(w * 0.20f, w * 0.20f)
    drawRoundRect(color = palette.bodyFill, topLeft = bodyTopLeft, size = bodySize, cornerRadius = corner)
    drawRoundRect(
        color = palette.outline,
        topLeft = bodyTopLeft,
        size = bodySize,
        cornerRadius = corner,
        style = Stroke(width = stroke),
    )
    // 眼睛:打盹闭眼线,其余大圆点(baby-schema:大而低)。
    val eyeY = h * 0.50f
    if (state == MascotState.Dozing) {
        drawLine(palette.outline, Offset(w * 0.32f, eyeY), Offset(w * 0.42f, eyeY), stroke, StrokeCap.Round)
        drawLine(palette.outline, Offset(w * 0.58f, eyeY), Offset(w * 0.68f, eyeY), stroke, StrokeCap.Round)
    } else {
        drawCircle(palette.outline, radius = w * 0.05f, center = Offset(w * 0.37f, eyeY))
        drawCircle(palette.outline, radius = w * 0.05f, center = Offset(w * 0.63f, eyeY))
    }
    // 腮红。
    drawCircle(palette.blushFill, radius = w * 0.05f, center = Offset(w * 0.27f, h * 0.60f))
    drawCircle(palette.blushFill, radius = w * 0.05f, center = Offset(w * 0.73f, h * 0.60f))
}

private const val MASCOT_TICK_MS = 200L
