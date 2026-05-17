package com.ticketbox.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppMotion
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

data class SwipeActionConfig(
    val icon: ImageVector,
    val label: String,
    val bg: Color,
    val fg: Color,
    val onTriggered: () -> Unit,
)

/**
 * 双向左右滑揭示 action 的列表行。
 * 手指向右滑 → 揭示左 bg → leftAction; 手指向左滑 → 揭示右 bg → rightAction.
 * enabled=false 彻底不绑手势 (与 BottomSheet 父手势避让).
 */
@Composable
fun SwipeableActionRow(
    modifier: Modifier = Modifier,
    leftAction: SwipeActionConfig? = null,
    rightAction: SwipeActionConfig? = null,
    onLongPress: (() -> Unit)? = null,
    enabled: Boolean = true,
    triggerThresholdFraction: Float = 0.35f,
    content: @Composable () -> Unit,
) {
    val haptics = rememberAppHaptics()
    val scope = rememberCoroutineScope()
    val offsetX = remember { Animatable(0f) }
    var rowWidthPx by remember { mutableIntStateOf(0) }
    val maxOffset = rowWidthPx.toFloat()
    val animSpec = tween<Float>(AppMotion.swipeRevealMillis, easing = AppMotion.easeStandard)

    LaunchedEffect(enabled) {
        if (!enabled && offsetX.value != 0f) offsetX.animateTo(0f, animSpec)
    }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .clipToBounds()
            .onSizeChanged { rowWidthPx = it.width },
    ) {
        SwipeActionBackground(leftAction, rightAction, offsetX.value)
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .offset { IntOffset(offsetX.value.roundToInt(), 0) }
                .pointerInput(enabled, onLongPress) {
                    if (!enabled || onLongPress == null) return@pointerInput
                    detectTapGestures(onLongPress = { onLongPress() })
                }
                .draggable(
                    enabled = enabled && (leftAction != null || rightAction != null),
                    orientation = Orientation.Horizontal,
                    state = rememberDraggableState { delta ->
                        scope.launch {
                            val newOffset = (offsetX.value + delta).coerceIn(
                                if (rightAction == null) 0f else -maxOffset,
                                if (leftAction == null) 0f else maxOffset,
                            )
                            offsetX.snapTo(newOffset)
                        }
                    },
                    onDragStopped = {
                        val threshold = maxOffset * triggerThresholdFraction
                        when {
                            offsetX.value > threshold && leftAction != null -> {
                                haptics.confirm()
                                offsetX.animateTo(0f, animSpec)
                                leftAction.onTriggered()
                            }
                            offsetX.value < -threshold && rightAction != null -> {
                                haptics.reject()
                                offsetX.animateTo(0f, animSpec)
                                rightAction.onTriggered()
                            }
                            else -> offsetX.animateTo(0f, animSpec)
                        }
                    },
                ),
        ) { content() }
    }
}

@Composable
private fun SwipeActionBackground(
    leftAction: SwipeActionConfig?,
    rightAction: SwipeActionConfig?,
    currentOffset: Float,
) {
    val showLeft = currentOffset > 0f && leftAction != null
    val showRight = currentOffset < 0f && rightAction != null
    when {
        showLeft && leftAction != null -> Box(
            modifier = Modifier.fillMaxSize().background(leftAction.bg),
            contentAlignment = Alignment.CenterStart,
        ) { ActionLabel(leftAction.icon, leftAction.label, leftAction.fg, alignedStart = true) }
        showRight && rightAction != null -> Box(
            modifier = Modifier.fillMaxSize().background(rightAction.bg),
            contentAlignment = Alignment.CenterEnd,
        ) { ActionLabel(rightAction.icon, rightAction.label, rightAction.fg, alignedStart = false) }
    }
}

@Composable
private fun ActionLabel(icon: ImageVector, label: String, fg: Color, alignedStart: Boolean) {
    val padding = if (alignedStart) PaddingValues(start = 24.dp, end = 16.dp) else PaddingValues(start = 16.dp, end = 24.dp)
    Row(
        modifier = Modifier.padding(padding),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(imageVector = icon, contentDescription = label, tint = fg)
        Text(text = label, color = fg, style = MaterialTheme.typography.labelLarge)
    }
}
