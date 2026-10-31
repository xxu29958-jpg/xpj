package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Paint
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathOperation
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

private val StubNotch = 12.dp
private val StubDotStep = 8.dp
private val StubDotRadius = 1.4.dp
private val StubFoot = 4.dp
private val StubShadowBlur = 8.dp
private val StubShadowDrop = 2.dp

/**
 * 票根: the record as a ticket stub. [body] is the paper part above a perforated
 * tear; [tail] is the kept part below it, finished with the coral foot of a kept
 * record. Without a tail the stub is a plain card with the foot. Decoration only:
 * the content keeps its own labels and semantics.
 *
 * The whole surface is drawn in one pass from the measured tear, so the notches
 * are right on the first frame without waiting for a recomposition.
 */
@Composable
fun TicketStub(
    modifier: Modifier = Modifier,
    tail: (@Composable () -> Unit)? = null,
    body: @Composable () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val paper = visuals.paperCard
    val edge = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft)
    val dots = MaterialTheme.colorScheme.outlineVariant
    val shadow = visuals.shadowTint.copy(alpha = AppAlpha.faint)
    val coral = visuals.clipCoral
    // Written by layout, read only while drawing: a draw invalidation, not a recomposition.
    var tearY by remember { mutableFloatStateOf(0f) }
    Column(
        modifier = modifier
            .fillMaxWidth()
            .drawBehind {
                val outline = stubOutline(size, AppRadius.hero.toPx(), StubNotch.toPx(), tearY.takeIf { tail != null })
                drawIntoCanvas { canvas ->
                    val lift = Paint().apply { color = paper }
                    lift.asFrameworkPaint().setShadowLayer(
                        StubShadowBlur.toPx(), 0f, StubShadowDrop.toPx(), shadow.toArgb(),
                    )
                    canvas.drawPath(outline, lift)
                }
                clipPath(outline) {
                    drawRect(coral, Offset(0f, size.height - StubFoot.toPx()), Size(size.width, StubFoot.toPx()))
                }
                drawPath(outline, edge, style = Stroke(1.dp.toPx()))
                if (tail != null && tearY > 0f) {
                    val inset = StubNotch.toPx() + StubDotStep.toPx()
                    var x = inset
                    while (x <= size.width - inset) {
                        drawCircle(dots, StubDotRadius.toPx(), Offset(x, tearY))
                        x += StubDotStep.toPx()
                    }
                }
            },
    ) {
        Box(Modifier.fillMaxWidth().onSizeChanged { tearY = it.height.toFloat() }.padding(AppSpacing.cardPadding)) {
            body()
        }
        if (tail != null) {
            Box(Modifier.fillMaxWidth().padding(AppSpacing.cardPadding).padding(bottom = StubFoot)) {
                tail()
            }
        }
    }
}

/** Rounded card minus a notch on each side at [tearY] (null: no tear). */
private fun stubOutline(size: Size, corner: Float, notch: Float, tearY: Float?): Path {
    val card = Path().apply { addRoundRect(RoundRect(Rect(Offset.Zero, size), CornerRadius(corner))) }
    val y = tearY?.takeIf { it > 0f && it < size.height } ?: return card
    val notches = Path().apply {
        addOval(Rect(Offset(0f, y), notch))
        addOval(Rect(Offset(size.width, y), notch))
    }
    return Path.combine(PathOperation.Difference, card, notches)
}
