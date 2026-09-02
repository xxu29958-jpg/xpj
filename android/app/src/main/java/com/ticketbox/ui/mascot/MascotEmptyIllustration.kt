package com.ticketbox.ui.mascot

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * 空态里的夹夹:打盹姿态([MascotState.Dozing] 闭眼),给各列表的「暂无数据」卡片
 * 一个有性格的插画,取代此前各屏自绘的图标插画。空态语义=没事干打盹,不需要事件机
 * (controller / one-shot),直接喂固定状态即可——欢迎挥手 / 确认撒花那类一次性动作走
 * [MascotController] 事件线,不在这里。
 *
 * 渲染是 [MascotArt] 图片宿主(品牌原生图片资产,paper/midnight 按渲染主题自动换源);
 * 消费面只关心 state。装饰性:文案卡片已用标题 + 正文表达空态含义,故用
 * [clearAndSetSemantics] 清空语义,让 TalkBack 跳过这张图,不重复播报。
 */
@Composable
fun MascotEmptyIllustration(
    modifier: Modifier = Modifier,
    size: Dp = 96.dp,
) {
    MascotArt(
        state = MascotState.Dozing,
        modifier = modifier.clearAndSetSemantics {},
        size = size,
    )
}
