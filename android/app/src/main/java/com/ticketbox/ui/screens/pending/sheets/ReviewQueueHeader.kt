package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R

/**
 * 连续审阅快补 sheet 的共享「外壳」：保存中标记 + 「还剩 N 条」计数 + 状态文案 +
 * 「跳过」回调。三个快补 sheet（金额/商家/分类）共用一份，既保证计数/跳过入口三端
 * 一致不分叉，也把每个 sheet 的参数表压在 detekt LongParameterList(≤5) 阈值内
 * （沿 ExpenseEditActionBarActions / BudgetEditorActions 的参数分组先例）。
 *
 * @param saving 当前票是否有保存请求在途（禁用跳过、按钮转「保存中」）。
 * @param remaining 本轮仍待补本字段的票数（含当前票）；<=0 时不显示计数行。
 * @param statusMessage 异步结果文案（主要是保存失败的留守反馈）；null/空不显示。
 */
internal data class ReviewSheetChrome(
    val saving: Boolean,
    val remaining: Int,
    val statusMessage: String?,
    val onSkip: () -> Unit,
)

/**
 * 快补 sheet 头部条：左侧「还剩 N 条」计数 + 右侧「跳过」。仅在队列里还有待补票
 * （[ReviewSheetChrome.remaining] > 0）时渲染；保存在途时禁用「跳过」避免与推进竞态。
 * 计数文案与下一条选择口径都由 VM 决定，本组件只显示。
 */
@Composable
internal fun ReviewQueueHeader(
    chrome: ReviewSheetChrome,
    modifier: Modifier = Modifier,
) {
    if (chrome.remaining <= 0) return
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(R.string.pending_review_queue_remaining, chrome.remaining),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        TextButton(
            onClick = chrome.onSkip,
            enabled = !chrome.saving,
        ) {
            Text(stringResource(R.string.pending_review_queue_skip_button))
        }
    }
}

/**
 * 快补 sheet 内的异步状态行（镜像批 9 编辑动作栏的消息锚定）：保存失败时把反馈钉在
 * sheet 内、按钮上沿，用户不离开当前票就能看到「为什么没存上」。
 *
 * 走中性 secondary 色（不染红）：与编辑动作栏的 statusMessage 同色规约。成功保存会
 * 推进 / 关闭并清掉文案，所以这里实际只在失败留守时出现。
 */
@Composable
internal fun ReviewSheetStatusMessage(
    chrome: ReviewSheetChrome,
    modifier: Modifier = Modifier,
) {
    val message = chrome.statusMessage
    if (message.isNullOrBlank()) return
    Text(
        text = message,
        color = MaterialTheme.colorScheme.secondary,
        style = MaterialTheme.typography.bodySmall,
        modifier = modifier,
    )
}
