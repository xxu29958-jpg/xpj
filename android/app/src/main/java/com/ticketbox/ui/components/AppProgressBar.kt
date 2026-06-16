package com.ticketbox.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.StateTone

/**
 * 通用进度条：圆角轨道 + counting-up 填充，颜色全走 [StateTone]（轨道 [StateTone.bg]、填充 [StateTone.fg]）。
 *
 * ADR-0049 §6.2 设计文档点名 8e-2 本应抽出的通用件——此前只有 `MemberSharedThingCard.kt` 里私有的
 * `CommunalProgressBar` 内联实现，8e-5 把那块 Box+Box 视觉抽到这里供计划级（hero，10dp）/ 每笔级（mini，4dp）
 * 复用，`CommunalProgressBar` 现委托本组件（视觉逐字节不变）。填充走 [StateTone]（成员/计划进度用 success 绿，
 * 作废/复核用 neutral），**绝不 danger**（红线②不 shame）。百分比/计数器留给调用方决定是否显示（成员债 §2.3 不显）。
 *
 * 动画用 [AppMotion.standardSpec]（tween normalMillis），与原 `CommunalProgressBar` 一致。可选
 * [contentDescription] 挂在轨道上供屏幕阅读器播报（成员债无百分比文本时尤其重要）。
 */
@Composable
fun AppProgressBar(
    fraction: Float,
    tone: StateTone,
    modifier: Modifier = Modifier,
    height: Dp = AppSpacing.contentGap,
    contentDescription: String? = null,
) {
    val animated by animateFloatAsState(
        targetValue = fraction.coerceIn(0f, 1f),
        animationSpec = AppMotion.standardSpec(),
        label = "appProgressBar",
    )
    val shape = RoundedCornerShape(AppRadius.small)
    val track = modifier
        .fillMaxWidth()
        .height(height)
        .clip(shape)
        .background(tone.bg)
        .then(
            if (contentDescription != null) {
                Modifier.semantics { this.contentDescription = contentDescription }
            } else {
                Modifier
            },
        )
    Box(modifier = track) {
        Box(
            modifier = Modifier
                .fillMaxWidth(animated)
                .fillMaxHeight()
                .clip(shape)
                .background(tone.fg),
        )
    }
}
