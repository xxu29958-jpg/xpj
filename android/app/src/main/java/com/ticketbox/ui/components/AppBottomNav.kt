package com.ticketbox.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandHorizontally
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.LocalThemeVisuals

data class AppBottomNavItem(
    val key: String,
    val label: String,
    val icon: ImageVector,
)

/**
 * 底部导航条。
 *
 * 设计取舍：
 * - 选中态 weight 从 1.28 降到 1.16，4-tab 时整体更平衡（28% 不对称视觉上抢镜）
 * - 选中态保持一致的 Row(icon+label) 结构，未选中态隐藏 label——避免布局类型互换造成跳动
 * - 用 [animateDpAsState] 平滑过渡 chip 宽度差，配合 [AnimatedVisibility] 让 label 横向 expand/shrink
 * - 选中瞬间 scale 弹簧反弹，给点击反馈
 * - 颜色 / 字重 / motion 都走 token：AppMotion.normalMillis、ThemeVisuals.primary
 */
@Composable
fun AppBottomNav(
    items: List<AppBottomNavItem>,
    selectedKey: String,
    onSelect: (AppBottomNavItem) -> Unit,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    val haptics = rememberAppHaptics()
    Box(
        modifier = modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 8.dp),
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(AppRadius.bottomBar),
            color = visuals.solidCard.copy(alpha = 0.995f),
            tonalElevation = 0.dp,
            shadowElevation = 0.dp,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                items.forEach { item ->
                    val selected = item.key == selectedKey
                    // 选中态 1.16，未选中态 1.0 —— 28% 太抢眼，降到 16% 仍可视别但平衡
                    val weight by animateDpAsState(
                        targetValue = if (selected) 116.dp else 100.dp,
                        animationSpec = spring(
                            dampingRatio = Spring.DampingRatioMediumBouncy,
                            stiffness = Spring.StiffnessMediumLow,
                        ),
                        label = "appBottomNavWeight",
                    )
                    Box(
                        modifier = Modifier
                            .weight(weight.value / 100f)
                            .height(48.dp)
                            .clickable(onClick = {
                                if (!selected) haptics.tick()
                                onSelect(item)
                            }),
                        contentAlignment = Alignment.Center,
                    ) {
                        AppBottomNavItemView(
                            item = item,
                            selected = selected,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun AppBottomNavItemView(
    item: AppBottomNavItem,
    selected: Boolean,
) {
    val visuals = LocalThemeVisuals.current
    val background by animateColorAsState(
        targetValue = if (selected) visuals.primary.copy(alpha = 0.90f) else Color.Transparent,
        animationSpec = tween(durationMillis = AppMotion.normalMillis),
        label = "appBottomNavBackground",
    )
    val content by animateColorAsState(
        targetValue = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
        animationSpec = tween(durationMillis = AppMotion.normalMillis),
        label = "appBottomNavContent",
    )
    // 选中瞬间 spring scale，给"已激活"的触觉反馈（搭配后续 haptic feedback）
    val scale by animateDpAsState(
        targetValue = if (selected) 102.dp else 100.dp,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioLowBouncy,
            stiffness = Spring.StiffnessMedium,
        ),
        label = "appBottomNavScale",
    )

    Row(
        modifier = Modifier
            .scale(scale.value / 100f)
            .height(40.dp)
            .clip(RoundedCornerShape(AppRadius.large))
            .background(background)
            .padding(horizontal = if (selected) 10.dp else 8.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = item.icon,
            contentDescription = item.label,
            tint = content,
            modifier = Modifier.size(if (selected) 18.dp else 20.dp),
        )
        AnimatedVisibility(
            visible = selected,
            enter = fadeIn(tween(AppMotion.normalMillis)) +
                expandHorizontally(tween(AppMotion.normalMillis)),
            exit = fadeOut(tween(AppMotion.fastMillis)) +
                shrinkHorizontally(tween(AppMotion.fastMillis)),
        ) {
            Text(
                text = item.label,
                color = content,
                style = MaterialTheme.typography.labelSmall.copy(
                    fontSize = 12.sp,
                    lineHeight = 15.sp,
                ),
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
