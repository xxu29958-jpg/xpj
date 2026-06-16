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
import com.ticketbox.viewmodel.DebtSettleCelebration
import kotlinx.coroutines.delay

/**
 * ADR-0049 §5（slice 8e-4）成员债「两清」庆祝覆盖层。事件驱动的一次性居中浮层（**不放 LazyColumn
 * item**——两清后内容不空，且独立成层避免顶破 [DebtDetailScreen] 的 LongMethod），由 [DebtRoute] 在详情屏
 * 之上叠一层 [Box] 调用，[celebration] 由 [com.ticketbox.viewmodel.DebtDetailViewModel] 的边沿检测产出。
 *
 * 浮现同一拍 [mascot] 收到 [MascotEvent.MilestoneReached]（夹夹撒花，对位 milestone-feedback 缺口，
 * §5.4）——这是第一个真实的 mascot emit 点；占位形象 [MascotPlaceholder] 是 ADR-0048 集成线的过渡渲染，
 * .riv 出炉后只换画布、不动这条事件接线。视觉撒花用通用 [ClearCelebration]，时长对齐
 * [MascotStateMachine.ONE_SHOT_DURATION_MS] 的 [MascotState.Celebrating]（3600ms，里程碑级隆重）。
 * 覆盖层用 [clearAndSetSemantics] 把整段并成一个 liveRegion 节点，让屏幕阅读器一次性播报里程碑（§5.5）。
 *
 * forgive 落地态虽也是 cleared，但 §5.6 走暖语分叉不撒花——边沿检测已加 `!isForgiven` 守卫，不会到这里。
 */
@Composable
internal fun DebtSettleCelebrationOverlay(
    celebration: DebtSettleCelebration?,
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
    val title = stringResource(R.string.debt_settle_celebration_title)
    val body = active.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?.let { stringResource(R.string.debt_settle_celebration_body_named, it) }
        ?: stringResource(R.string.debt_settle_celebration_body)
    val announce = stringResource(R.string.debt_settle_celebration_announce)
    val checkDescription = stringResource(R.string.debt_settle_celebration_check_desc)
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
