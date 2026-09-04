package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.BackgroundTransform
import com.ticketbox.ui.appearance.background.BackgroundTransformGeometry
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing

/** Point-and-click alternatives to pan/pinch, using the renderer's transform geometry. */
@Composable
internal fun BackgroundEditorCompositionControls(
    transform: BackgroundTransform,
    enabled: Boolean,
    onTransformChange: (BackgroundTransform) -> Unit,
) {
    BackgroundEditorZoomControls(transform, enabled, onTransformChange)
    BackgroundEditorNudgeControls(transform, enabled, onTransformChange)
    BackgroundEditorAnchorControls(transform, onTransformChange)
}

@Composable
private fun BackgroundEditorZoomControls(
    transform: BackgroundTransform,
    enabled: Boolean,
    onTransformChange: (BackgroundTransform) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        BackgroundActionButton(
            text = stringResource(R.string.background_editor_zoom_out),
            modifier = Modifier.weight(1f),
            enabled = enabled && transform.scale > BackgroundTransformGeometry.MIN_SCALE,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.zoomed(transform, 1f / BackgroundTransformGeometry.ZOOM_STEP),
                )
            },
        )
        BackgroundActionButton(
            text = stringResource(R.string.background_editor_reset),
            modifier = Modifier.weight(1f),
            enabled = enabled && transform != BackgroundTransform(),
            onClick = { onTransformChange(BackgroundTransform()) },
        )
        BackgroundActionButton(
            text = stringResource(R.string.background_editor_zoom_in),
            modifier = Modifier.weight(1f),
            enabled = enabled && transform.scale < BackgroundTransformGeometry.MAX_SCALE,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.zoomed(transform, BackgroundTransformGeometry.ZOOM_STEP),
                )
            },
        )
    }
}

@Composable
private fun BackgroundEditorNudgeControls(
    transform: BackgroundTransform,
    enabled: Boolean,
    onTransformChange: (BackgroundTransform) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap, Alignment.CenterHorizontally),
    ) {
        BackgroundEditorNudgeButton(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
            contentDescription = stringResource(R.string.background_editor_nudge_left),
            enabled = enabled,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.nudged(transform, -BackgroundTransformGeometry.OFFSET_STEP, 0f),
                )
            },
        )
        BackgroundEditorNudgeButton(
            imageVector = Icons.Filled.KeyboardArrowUp,
            contentDescription = stringResource(R.string.background_editor_nudge_up),
            enabled = enabled,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.nudged(transform, 0f, -BackgroundTransformGeometry.OFFSET_STEP),
                )
            },
        )
        BackgroundEditorNudgeButton(
            imageVector = Icons.Filled.KeyboardArrowDown,
            contentDescription = stringResource(R.string.background_editor_nudge_down),
            enabled = enabled,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.nudged(transform, 0f, BackgroundTransformGeometry.OFFSET_STEP),
                )
            },
        )
        BackgroundEditorNudgeButton(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = stringResource(R.string.background_editor_nudge_right),
            enabled = enabled,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.nudged(transform, BackgroundTransformGeometry.OFFSET_STEP, 0f),
                )
            },
        )
    }
}

@Composable
private fun BackgroundEditorAnchorControls(
    transform: BackgroundTransform,
    onTransformChange: (BackgroundTransform) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        AppFilterChip(
            modifier = Modifier.weight(1f),
            label = stringResource(R.string.background_editor_anchor_top),
            selected = transform.offsetY <= -1f + 0.01f,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.clamped(transform.copy(offsetY = -1f)),
                )
            },
        )
        AppFilterChip(
            modifier = Modifier.weight(1f),
            label = stringResource(R.string.background_editor_anchor_center),
            selected = kotlin.math.abs(transform.offsetY) < 0.01f,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.clamped(transform.copy(offsetY = 0f)),
                )
            },
        )
        AppFilterChip(
            modifier = Modifier.weight(1f),
            label = stringResource(R.string.background_editor_anchor_bottom),
            selected = transform.offsetY >= 1f - 0.01f,
            onClick = {
                onTransformChange(
                    BackgroundTransformGeometry.clamped(transform.copy(offsetY = 1f)),
                )
            },
        )
    }
}

@Composable
private fun BackgroundEditorNudgeButton(
    imageVector: ImageVector,
    contentDescription: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    IconButton(onClick = onClick, enabled = enabled) {
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(
                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = AppAlpha.medium),
                )
                .padding(AppSpacing.smallGap),
        ) {
            Icon(imageVector = imageVector, contentDescription = contentDescription)
        }
    }
}
