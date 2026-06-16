package com.ticketbox.ui.components

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
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * 通用「清零/两清」庆祝动画。
 *
 * 从 [com.ticketbox.ui.screens.pending.PendingClearCelebration] 抽出（视觉 / 时长 / 三主题色逐字节一致，
 * 仅把文案参数化），让待确认清空（pending）与成员债两清（ADR-0049 §5 / slice 8e-4，
 * [com.ticketbox.ui.screens.DebtSettleCelebrationOverlay]）共用同一份动画体；§5.7 的「单笔两清 / 计划达成 /
 * AllDebtsCleared」三处也复用本组件。
 *
 * 视觉：
 * - 中央 check 图标 scale 0.4 → 1.0 弹簧反弹
 * - 周围 12 颗微小圆点呈放射状放大 + 渐淡退出（[Animatable] 驱动 0→1）
 * - 触感 haptic.confirm()
 *
 * 设计取舍：
 * - 不使用 Lottie：避免引一个 .json 资产文件；本地 Canvas 绘制足够表达「完成」语义。未来如果想换成更精致的
 *   Lottie，把这个文件 swap 成 [com.airbnb.lottie.compose.LottieAnimation] 即可，调用方接口不变。
 * - 复用 ThemeVisuals.primary / illustrationTint，三套主题色都能 work。
 * - 不上音效（一般用户不会喜欢账单 app 突然响）。
 */
@Composable
fun ClearCelebration(
    visible: Boolean,
    title: String,
    body: String,
    checkDescription: String,
) {
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
                    CheckBubble(description = checkDescription)
                }
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.hero.weight,
                    color = MaterialTheme.colorScheme.primary,
                )
                Text(
                    text = body,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun CheckBubble(description: String) {
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
            contentDescription = description,
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
