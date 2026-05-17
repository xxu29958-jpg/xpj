package com.ticketbox.ui.components

import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import com.ticketbox.ui.design.AppElevation
import com.ticketbox.ui.design.AppMotion
import kotlin.math.roundToInt

/**
 * 长按拾起 + 拖动排序的通用列表。不引第三方库 (V0.10 硬约束)。
 * 调用方按自家 row 实际高度传入 [estimatedItemHeight]; DashboardCardRow 等 8 张同高卡片够用。
 * content lambda 提供 (index, item, isDragging), 便于消费方计算 canMoveUp/canMoveDown。
 */
@Composable
fun <T : Any> DraggableReorderColumn(
    items: List<T>,
    key: (T) -> Any,
    onMove: (from: Int, to: Int) -> Unit,
    modifier: Modifier = Modifier,
    spacing: Dp = 12.dp,
    estimatedItemHeight: Dp = 72.dp,
    enabled: Boolean = true,
    content: @Composable (index: Int, item: T, isDragging: Boolean) -> Unit,
) {
    val haptics = rememberAppHaptics()
    val density = LocalDensity.current
    var draggingIndex by remember { mutableStateOf<Int?>(null) }
    var dragOffsetY by remember { mutableFloatStateOf(0f) }
    val rowStepPx = with(density) { (estimatedItemHeight + spacing).toPx() }

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(spacing),
    ) {
        items.forEachIndexed { index, item ->
            val itemKey = remember(item) { key(item) }
            val isDragging = draggingIndex == index
            val liftElevation by animateDpAsState(
                targetValue = if (isDragging) AppElevation.draggingCard else 0.dp,
                animationSpec = tween(AppMotion.dragLiftMillis, easing = AppMotion.easeOvershoot),
                label = "drag-lift-elevation",
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .zIndex(if (isDragging) 1f else 0f)
                    .offset { IntOffset(0, if (isDragging) dragOffsetY.roundToInt() else 0) }
                    .shadow(elevation = liftElevation)
                    .pointerInput(itemKey, enabled, items.size) {
                        if (!enabled) return@pointerInput
                        detectDragGesturesAfterLongPress(
                            onDragStart = { draggingIndex = index; dragOffsetY = 0f; haptics.tick() },
                            onDragEnd = { draggingIndex = null; dragOffsetY = 0f },
                            onDragCancel = { draggingIndex = null; dragOffsetY = 0f },
                            onDrag = { _, drag ->
                                dragOffsetY += drag.y
                                var current = draggingIndex ?: return@detectDragGesturesAfterLongPress
                                val half = rowStepPx / 2f
                                while (dragOffsetY > half && current < items.lastIndex) {
                                    onMove(current, current + 1)
                                    current += 1
                                    draggingIndex = current
                                    dragOffsetY -= rowStepPx
                                }
                                while (dragOffsetY < -half && current > 0) {
                                    onMove(current, current - 1)
                                    current -= 1
                                    draggingIndex = current
                                    dragOffsetY += rowStepPx
                                }
                            },
                        )
                    },
            ) {
                content(index, item, isDragging)
            }
        }
    }
}
