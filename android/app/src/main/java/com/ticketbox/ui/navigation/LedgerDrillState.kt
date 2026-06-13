package com.ticketbox.ui.navigation

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * §三报表钻取:统计分类行点击 → 账本页带筛选打开的一次性请求。
 *
 * @property month 统计页当时的月份(`yyyy-MM`),落到账本月份筛选。
 * @property category 被点的分类,落到账本分类筛选。
 */
internal data class LedgerDrillRequest(
    val month: String,
    val category: String,
)

/**
 * 一次性钻取请求的可消费持有者(镜像 [LaunchActionState] 的单槽 post/consume 形态):
 * StatsRoute 在分类行点击时 [post] 并切到账本 tab;LedgerRoute 的 LaunchedEffect [consume]
 * (取走即清),消费后即不再触发——避免 Route 重入(tab 切换 AnimatedContent 过场、
 * 局部 remember 丢失)时拿旧值重复覆盖用户随后手改的筛选。
 *
 * 单槽语义(有意,非队列):连点两个分类只保留最后一个——目标页只有一套筛选,队列无意义。
 * 单独成类(而非塞进 MainShellState):后者已贴着 detekt 每文件函数上限(LaunchActionState 同因)。
 */
internal class LedgerDrillState {
    var pending by mutableStateOf<LedgerDrillRequest?>(null)
        private set

    fun post(request: LedgerDrillRequest) {
        pending = request
    }

    /** 取走待处理钻取请求并清空。 */
    fun consume(): LedgerDrillRequest? {
        val request = pending ?: return null
        pending = null
        return request
    }
}
