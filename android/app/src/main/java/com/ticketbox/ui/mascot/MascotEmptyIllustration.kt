package com.ticketbox.ui.mascot

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals

/**
 * 空态里的夹夹:静态打盹剪影([MascotState.Dozing] 闭眼),给各列表的「暂无数据」卡片
 * 一个有性格的占位,取代此前各屏自绘的图标插画。空态语义=没事干打盹,不需要事件机
 * (controller / one-shot),直接喂固定状态即可——欢迎挥手 / 确认撒花那类一次性动作走
 * [MascotController] 事件线,不在这里。
 *
 * 配色走 [mascotPalette] 单源(三主题 paper/mono/midnight 自动换色),禁止另起映射。
 * 渲染是 [MascotPlaceholder] 占位画布,.riv 出炉后(ADR-0048)只换画布、不动这条接线。
 * 装饰性:文案卡片已用标题 + 正文表达空态含义,故用 [clearAndSetSemantics] 清空语义,
 * 让 TalkBack 跳过这张图,不重复播报。
 */
@Composable
fun MascotEmptyIllustration(
    modifier: Modifier = Modifier,
    size: Dp = 96.dp,
) {
    MascotPlaceholder(
        state = MascotState.Dozing,
        palette = mascotPalette(LocalThemeVisuals.current, LocalStateTokens.current),
        modifier = modifier.clearAndSetSemantics {},
        size = size,
    )
}
