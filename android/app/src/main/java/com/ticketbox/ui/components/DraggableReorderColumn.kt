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

data class DraggableReorderItems<T : Any>(
    val values: List<T>,
    val key: (T) -> Any,
)

data class DraggableReorderBehavior(
    val onMove: (from: Int, to: Int) -> Unit,
    val enabled: Boolean = true,
)

data class DraggableReorderLayout(
    val spacing: Dp = 12.dp,
    val estimatedItemHeight: Dp = 72.dp,
)

/**
 * 长按拾起 + 拖动排序的通用列表。不引第三方库 (V0.10 硬约束)。
 * 调用方按自家 row 实际高度传入 [DraggableReorderLayout.estimatedItemHeight]。
 * content lambda 提供 (index, item, isDragging), 便于消费方计算 canMoveUp/canMoveDown。
 */
@Composable
fun <T : Any> DraggableReorderColumn(
    items: DraggableReorderItems<T>,
    behavior: DraggableReorderBehavior,
    modifier: Modifier = Modifier,
    layout: DraggableReorderLayout = DraggableReorderLayout(),
    content: @Composable (index: Int, item: T, isDragging: Boolean) -> Unit,
) {
    val haptics = rememberAppHaptics()
    val density = LocalDensity.current
    var draggingIndex by remember { mutableStateOf<Int?>(null) }
    var dragOffsetY by remember { mutableFloatStateOf(0f) }
    val rowStepPx = with(density) { (layout.estimatedItemHeight + layout.spacing).toPx() }

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(layout.spacing),
    ) {
        items.values.forEachIndexed { index, item ->
            val itemKey = remember(item) { items.key(item) }
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
                    .pointerInput(itemKey, behavior.enabled, items.values.size) {
                        if (!behavior.enabled) return@pointerInput
                        detectDragGesturesAfterLongPress(
                            onDragStart = { draggingIndex = index; dragOffsetY = 0f; haptics.tick() },
                            onDragEnd = { draggingIndex = null; dragOffsetY = 0f },
                            onDragCancel = { draggingIndex = null; dragOffsetY = 0f },
                            onDrag = { _, drag ->
                                dragOffsetY += drag.y
                                var current = draggingIndex ?: return@detectDragGesturesAfterLongPress
                                val half = rowStepPx / 2f
                                while (dragOffsetY > half && current < items.values.lastIndex) {
                                    behavior.onMove(current, current + 1)
                                    current += 1
                                    draggingIndex = current
                                    dragOffsetY -= rowStepPx
                                }
                                while (dragOffsetY < -half && current > 0) {
                                    behavior.onMove(current, current - 1)
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
