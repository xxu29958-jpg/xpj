package com.ticketbox.ui.screens.pending

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.rememberAppHaptics
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * 待确认清零庆祝动画。
 *
 * 触发：从「有待确认」过渡到「全部清零」的瞬间。1.5s 后自动隐藏，余下露出静态 empty state。
 *
 * 视觉：
 * - 中央 check 图标 scale 0.4 → 1.0 弹簧反弹
 * - 周围 12 颗微小圆点呈放射状以放大 + 渐淡退出（用 [Animatable] 驱动 0→1）
 * - 触感 haptic.confirm()
 *
 * 设计取舍：
 * - 不使用 Lottie：避免引一个 .json 资产文件；本地 Canvas 绘制足够表达「完成」语义。
 *   未来如果想换成更精致的 Lottie，把这个文件 swap 成 [com.airbnb.lottie.compose.LottieAnimation]
 *   即可，调用方接口不变。
 * - 复用 ThemeVisuals.primary / illustrationTint，三套主题色都能 work。
 * - 不上音效（一般用户不会喜欢账单 app 突然响）。
 */
@Composable
internal fun PendingClearCelebration(visible: Boolean) {
    val haptics = rememberAppHaptics()
    val confettiProgress = remember { Animatable(0f) }
    LaunchedEffect(visible) {
        if (visible) {
            haptics.confirm()
            confettiProgress.snapTo(0f)
            confettiProgress.animateTo(
                targetValue = 1f,
                animationSpec = tween(durationMillis = AppMotion.slowMillis * 3, easing = LinearEasing),
            )
        } else {
            confettiProgress.snapTo(0f)
        }
    }

    AnimatedVisibility(
        visible = visible,
        enter = fadeIn(tween(AppMotion.fastMillis)) +
            scaleIn(initialScale = 0.92f, animationSpec = tween(AppMotion.fastMillis)),
        exit = fadeOut(tween(AppMotion.normalMillis)) +
            scaleOut(targetScale = 0.96f, animationSpec = tween(AppMotion.normalMillis)),
    ) {
        AppContentCard {
            Column(
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 8.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Box(
                    modifier = Modifier.size(96.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Confetti(progress = confettiProgress.value)
                    CheckBubble()
                }
                Text(
                    text = "全部处理完了",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.hero.weight,
                    color = MaterialTheme.colorScheme.primary,
                )
                Text(
                    text = "待确认队列清空。新截图来了会出现在这里。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}
@Composable
private fun CheckBubble() {
    val visuals = LocalThemeVisuals.current
    Box(
        modifier = Modifier
            .size(56.dp)
            .clip(CircleShape)
            .background(visuals.primary.copy(alpha = 0.90f)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = Icons.Filled.Check,
            contentDescription = "全部完成",
            tint = MaterialTheme.colorScheme.onPrimary,
            modifier = Modifier.size(32.dp),
        )
    }
}

@Composable
private fun Confetti(progress: Float) {
    val visuals = LocalThemeVisuals.current
    val palette = remember {
        listOf(
            visuals.primary,
            visuals.accent,
            visuals.warmMist,
            visuals.illustrationTint,
        )
    }
    Canvas(modifier = Modifier.fillMaxSize()) {
        if (progress <= 0f) return@Canvas
        val centerX = size.width / 2f
        val centerY = size.height / 2f
        val maxRadius = size.minDimension * 0.48f
        val particleSize = 5f
        repeat(12) { i ->
            val angle = (i / 12.0) * 2 * PI
            val radius = maxRadius * progress
            val x = centerX + cos(angle).toFloat() * radius
            val y = centerY + sin(angle).toFloat() * radius
            val alpha = (1f - progress).coerceIn(0f, 1f)
            drawCircle(
                color = palette[i % palette.size].copy(alpha = alpha),
                radius = particleSize,
                center = Offset(x, y),
            )
        }
    }
}
