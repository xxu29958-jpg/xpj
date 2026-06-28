package com.ticketbox.ui.mascot

import android.os.SystemClock
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
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
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

/**
 * 夹夹的 Compose 持有者:把 app 事件喂给 [MascotStateMachine],按节拍推进
 * 过期回落,向 UI 暴露当前 [MascotState]。渲染端只消费 state + palette,
 * 不回写任何业务状态。
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
 * 原生 Compose 夹夹渲染器。
 *
 * 名称保留为 MascotPlaceholder 是为了不扩散调用点,但 Rive 放弃后它已是正式渲染器:
 * 参考 MASCOT_BRIEF §1-§7,用 token 化 Canvas 画出长尾夹身体、顶部金属丝手臂、
 * 小票、夹口、脚、五官和状态道具。动效保持轻量,只表达状态反馈,不做页面级编舞。
 */
@Composable
fun MascotPlaceholder(
    state: MascotState,
    palette: MascotPalette,
    modifier: Modifier = Modifier,
    size: Dp = 96.dp,
) {
    val transition = rememberInfiniteTransition(label = "mascot-motion")
    val breath by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(MASCOT_BREATH_MS, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "breath",
    )
    val zzzPhase by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(MASCOT_ZZZ_MS, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "zzz",
    )
    Canvas(modifier = modifier.size(size)) {
        drawJiajiaV4Vector(state, palette, breath, zzzPhase)
    }
}

private const val MASCOT_TICK_MS = 200L
private const val MASCOT_BREATH_MS = 2400
private const val MASCOT_ZZZ_MS = 2800
