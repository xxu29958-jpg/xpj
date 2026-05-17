package com.ticketbox.ui.components

import android.os.Build
import android.view.HapticFeedbackConstants
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.hapticfeedback.HapticFeedback
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalView

/**
 * 触感反馈语义化封装。
 *
 * 设计取舍：
 * - Compose 自带 [HapticFeedback] 只暴露 LongPress / TextHandleMove 两种 type，
 *   信息量不够。我们在 API 30+ 用平台 [HapticFeedbackConstants]（CONFIRM、REJECT、
 *   GESTURE_END）拿到「确认 / 拒绝 / 收尾」语义化反馈，旧设备回退到 Compose 的 LongPress。
 * - 调用方按场景挑 type，而不是直接 perform —— 比如「确认入账」用 [confirm]，
 *   「拒绝 / 删除」用 [reject]，「按钮点击 / tab 切换」用 [tick]。
 * - 所有反馈都是「打点」级别，绝不在 hot loop（拖动 / 滚动）里调用，避免震动疲劳。
 */
class AppHaptics internal constructor(
    private val composeHaptic: HapticFeedback,
    private val view: android.view.View?,
) {
    /**
     * 「确认入账」/「保存成功」/「上传成功」。平台 API 30+ 有真正的双击节奏，
     * 旧设备回退 LongPress（短而结实的一下）。
     */
    fun confirm() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && view != null) {
            view.performHapticFeedback(HapticFeedbackConstants.CONFIRM)
        } else {
            composeHaptic.performHapticFeedback(HapticFeedbackType.LongPress)
        }
    }

    /**
     * 「拒绝」/「删除」/「撤销」。平台 API 30+ 是「拒绝模式」的双震，旧设备保持 LongPress。
     */
    fun reject() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && view != null) {
            view.performHapticFeedback(HapticFeedbackConstants.REJECT)
        } else {
            composeHaptic.performHapticFeedback(HapticFeedbackType.LongPress)
        }
    }

    /**
     * 「按钮点击」/「tab 切换」/「toggle 状态」。极轻一下，给点存在感但不打扰。
     */
    fun tick() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && view != null) {
            view.performHapticFeedback(HapticFeedbackConstants.GESTURE_END)
        } else {
            composeHaptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
        }
    }
}

@Composable
fun rememberAppHaptics(): AppHaptics {
    val composeHaptic = LocalHapticFeedback.current
    val view = LocalView.current
    return remember(composeHaptic, view) {
        AppHaptics(composeHaptic = composeHaptic, view = view)
    }
}
