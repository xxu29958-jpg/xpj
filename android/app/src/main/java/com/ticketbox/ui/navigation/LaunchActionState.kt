package com.ticketbox.ui.navigation

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * 系统分享 / 启动器 shortcut 经 MainShell 派发给具体 Route 的一次性入口动作（W1）。
 * 每个变体由对应 Route 负责消费：
 *  - [UploadSharedImages] / [OpenImagePicker] → PendingRoute。
 *  - [OpenManualEntry] → 账本页（LedgerScreen 的记一笔表单）。
 */
internal sealed interface LaunchAction {
    /** 系统分享带进来的图（已 sanitize 的 uri 字符串）；顺序上传。 */
    data class UploadSharedImages(val uris: List<String>) : LaunchAction

    /** 「传小票」shortcut：拉起系统图片选择。 */
    object OpenImagePicker : LaunchAction

    /** 「记一笔」shortcut：打开手动记账表单。 */
    object OpenManualEntry : LaunchAction
}

/**
 * 一次性入口动作的可消费持有者（W1）。MainShell 的 LaunchedEffect [post] 写入；目标 Route
 * 的 LaunchedEffect 只在动作是**自己负责的变体**时才 [consume]（取走即清），不是自己的就
 * 留给对的 Route——tab 是 AnimatedContent 过场时新旧两 Route 短暂共存也不会被错的一方吞掉。
 * 状态挂在这里（由 MainShellState 持有、跨 tab 存活），消费后即不再触发——避免裸 revision/
 * bool 在 Route 重入（局部 remember 丢失）时拿旧值重复弹选择器/表单/上传。
 *
 * 单独成类（而非塞进 MainShellState）是因为后者已贴着 detekt 每文件函数上限。
 */
internal class LaunchActionState {
    var pending by mutableStateOf<LaunchAction?>(null)
        private set

    fun post(action: LaunchAction) {
        pending = action
    }

    /** 取走待处理入口动作并清空（调用方应已确认是自己负责的变体）。 */
    fun consume(): LaunchAction? {
        val action = pending ?: return null
        pending = null
        return action
    }
}
