package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.appearance.background.LocalCanvasPhotoState
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.asTextStyle
import kotlin.math.roundToInt

/**
 * The root domain header (D01–D05), shared by the shell and the background preview so both show
 * the same result. With a measured photo it becomes the photo window: transparent, no divider,
 * a window sized by immersion, and its bottom edge reported to the canvas so only this band is
 * veiled to the large-text target. It carries just the large title and icon actions.
 */
@Composable
fun AppDomainHeader(
    title: String,
    modifier: Modifier = Modifier,
    actions: @Composable RowScope.() -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val canvas = LocalCanvasPhotoState.current
    val photoWindow = canvas?.photoActive == true
    DisposableEffect(canvas) { onDispose { canvas?.headerBandPx = 0 } }
    SideEffect { if (!photoWindow) canvas?.headerBandPx = 0 }
    Surface(
        modifier = modifier.onGloballyPositioned { coordinates ->
            if (photoWindow) canvas.headerBandPx = coordinates.boundsInRoot().bottom.roundToInt()
        },
        color = if (photoWindow) Color.Transparent else visuals.surfaceNav.copy(alpha = AppAlpha.opaque),
        tonalElevation = AppSpacing.none,
        shadowElevation = AppSpacing.none,
    ) {
        Column(modifier = Modifier.fillMaxWidth().statusBarsPadding()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = AppSpacing.controlMinHeight)
                    .padding(horizontal = AppSpacing.screenHorizontal),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = title,
                    modifier = Modifier.weight(1f),
                    color = visuals.primary,
                    style = AppTypography.pageTitle.asTextStyle(),
                )
                actions()
            }
            if (photoWindow) {
                Spacer(Modifier.height(photoWindowHeight(requireNotNull(canvas).immersion)))
            } else {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
            }
        }
    }
}

/** How much of the photo the root header shows: more for atmosphere, a sliver for focus. */
private fun photoWindowHeight(mode: ImmersionMode): Dp = when (mode) {
    ImmersionMode.Atmosphere -> 72.dp
    ImmersionMode.Balanced -> 40.dp
    ImmersionMode.Focus -> 12.dp
}
