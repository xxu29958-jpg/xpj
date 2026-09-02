package com.ticketbox.ui.mascot

import android.os.SystemClock
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

/**
 * 夹夹的 Compose 持有者:把 app 事件喂给 [MascotStateMachine],按节拍推进
 * 过期回落,向 UI 暴露当前 [MascotState]。渲染端([MascotArt])只消费 state,
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

private const val MASCOT_TICK_MS = 200L
