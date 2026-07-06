package com.ticketbox.ui.components

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.semantics

@Composable
fun Modifier.appTapWithoutDrag(
    enabled: Boolean,
    onTap: () -> Unit,
): Modifier {
    if (!enabled) return this
    val touchSlop = LocalViewConfiguration.current.touchSlop
    return this
        .semantics {
            onClick {
                onTap()
                true
            }
        }
        .pointerInput(touchSlop, onTap) {
            awaitEachGesture {
                val down = awaitFirstDown(requireUnconsumed = false)
                val start = down.position
                var dragged = false
                while (true) {
                    val change = awaitPointerEvent()
                        .changes
                        .firstOrNull { it.id == down.id }
                        ?: return@awaitEachGesture
                    if (change.isConsumed) return@awaitEachGesture
                    if ((change.position - start).getDistance() > touchSlop) dragged = true
                    if (!change.pressed) {
                        if (!dragged) {
                            onTap()
                            change.consume()
                        }
                        return@awaitEachGesture
                    }
                }
            }
        }
}
