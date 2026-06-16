package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.ClearCelebration
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.mascot.MascotController
import com.ticketbox.ui.mascot.MascotEvent
import com.ticketbox.ui.mascot.MascotPlaceholder
import com.ticketbox.ui.mascot.MascotState
import com.ticketbox.ui.mascot.MascotStateMachine
import com.ticketbox.ui.mascot.mascotPalette
import com.ticketbox.viewmodel.DebtGoalCelebration
import kotlinx.coroutines.delay

/**
 * ADR-0049 §6.6（slice 8e-5）整个还债**计划**达成的撒花覆盖层 —— 比单笔两清（⑤ [DebtSettleCelebrationOverlay]）
 * 高一档的庆祝，文案强调「这几笔一起完成」。事件驱动的一次性居中浮层，由 [DebtGoalRoute] 在 [DebtGoalScreen]
 * 之上叠一层 [Box] 调用，[celebration] 由 [com.ticketbox.viewmodel.DebtGoalViewModel] 在「未达成 → 达成」
 * 边沿（**只读服务端 evaluation_state**）且成分为**纯成员**时产出（外部/混装走轻量 flashMessage，不到这里，§6.7）。
 *
 * 浮现同一拍 [mascot] 收到 [MascotEvent.MilestoneReached]（夹夹撒花，荣誉归双方与关系，非奖励「催到钱」，
 * MASCOT_BRIEF §4.1）。视觉复用通用 [ClearCelebration]，时长对齐 [MascotStateMachine.ONE_SHOT_DURATION_MS] 的
 * [MascotState.Celebrating]（3600ms，里程碑级隆重）；占位形象 [MascotPlaceholder] 是 ADR-0048 集成线的过渡渲染。
 * 用 [clearAndSetSemantics] 把整段并成一个 Polite liveRegion 节点，让屏幕阅读器一次性、不打断地播报里程碑。
 *
 * 与 ⑤ 的单笔浮层并行而独立（不同路由、不同文案；§6.6「单笔两清的喜悦由详情屏 ⑤ 独占」，⑥ 只在整个计划达成时撒）。
 */
@Composable
internal fun DebtGoalCelebrationOverlay(
    celebration: DebtGoalCelebration?,
    mascot: MascotController,
    onConsume: () -> Unit,
) {
    var visible by remember { mutableStateOf(false) }
    LaunchedEffect(celebration) {
        if (celebration == null) return@LaunchedEffect
        visible = true
        mascot.onEvent(MascotEvent.MilestoneReached)
        delay(MascotStateMachine.ONE_SHOT_DURATION_MS.getValue(MascotState.Celebrating))
        visible = false
        // 让 ClearCelebration 的退出动画播完再拆掉浮层（此前 celebration 仍非空、组件仍在树上）。
        delay(AppMotion.normalMillis.toLong())
        onConsume()
    }

    val active = celebration ?: return
    val title = stringResource(R.string.debt_plan_celebration_title)
    val body = active.goalName.takeIf { it.isNotBlank() }
        ?.let { stringResource(R.string.debt_plan_celebration_body_named, it) }
        ?: stringResource(R.string.debt_plan_celebration_body)
    val announce = stringResource(R.string.debt_plan_celebration_announce)
    val checkDescription = stringResource(R.string.debt_plan_celebration_check_desc)
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = AppSpacing.cardPadding)
            .clearAndSetSemantics {
                // Polite（非 Assertive）：正向、非紧急的里程碑不该打断屏幕阅读器正在说的话，契合 §0 暖意红线。
                liveRegion = LiveRegionMode.Polite
                contentDescription = announce
            },
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            MascotPlaceholder(
                state = mascot.state,
                palette = mascotPalette(LocalThemeVisuals.current, LocalStateTokens.current),
                size = 72.dp,
            )
            ClearCelebration(
                visible = visible,
                title = title,
                body = body,
                checkDescription = checkDescription,
            )
        }
    }
}
