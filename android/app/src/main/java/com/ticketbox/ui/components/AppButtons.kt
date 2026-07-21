package com.ticketbox.ui.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals

private const val ControlBorderIdleAlpha = 0.46f
private const val ControlBorderPressedAlpha = 0.82f
private const val ControlContainerIdleAlpha = 0.98f
private const val ControlContainerPressedAlpha = 1f

data class AppOutlinedButtonOptions(
    val enabled: Boolean = true,
    val danger: Boolean = false,
    val contentPadding: PaddingValues = PaddingValues(
        horizontal = AppSpacing.compactGap,
        vertical = AppSpacing.miniGap,
    ),
)

@Composable
fun AppPrimaryButton(
    text: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.small)
    Box(
        modifier = modifier
            .height(AppSpacing.controlMinHeight)
            .clip(shape)
            .background(visuals.primary)
            .border(
                width = AppButtonTokens.BorderWidth,
                color = visuals.primaryDark.copy(alpha = 0.74f),
                shape = shape,
            )
            .alpha(if (enabled) 1f else 0.58f)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onPrimary,
                modifier = Modifier.size(AppIconSize.standard),
            )
            Text(
                text = text,
                color = MaterialTheme.colorScheme.onPrimary,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
fun PrimaryCtaButton(
    text: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    AppPrimaryButton(text = text, icon = icon, modifier = modifier, enabled = enabled, onClick = onClick)
}

@Composable
fun AppBackButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clearAndSetSemantics {
                contentDescription = text
                role = Role.Button
                onClick(action = {
                    onClick()
                    true
                })
            }
            .size(AppSpacing.controlMinHeight)
            .clip(CircleShape)
            .clickable(role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(AppButtonTokens.BackVisualSize)
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.surfaceContainerLow)
                .border(
                    width = AppButtonTokens.BorderWidth,
                    color = MaterialTheme.colorScheme.outlineVariant,
                    shape = CircleShape,
                ),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(AppIconSize.standard),
            )
        }
    }
}

@Composable
fun QuietOutlinedButton(
    text: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    leadingIcon: ImageVector? = null,
    onClick: () -> Unit,
) {
    AppOutlinedButton(
        modifier = modifier.defaultMinSize(minHeight = AppSpacing.controlMinHeight),
        options = AppOutlinedButtonOptions(
            enabled = enabled,
            contentPadding = PaddingValues(
                horizontal = AppSpacing.compactGap,
                vertical = AppSpacing.miniGap,
            ),
        ),
        onClick = onClick,
    ) {
        leadingIcon?.let {
            Icon(it, contentDescription = null, modifier = Modifier.size(AppIconSize.compact))
            Box(modifier = Modifier.width(AppSpacing.smallGap))
        }
        Text(
            text = text,
            style = MaterialTheme.typography.labelLarge,
            autoSize = TextAutoSize.StepBased(minFontSize = 11.sp, maxFontSize = 14.sp, stepSize = 1.sp),
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            softWrap = false,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
fun AppOutlinedButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    options: AppOutlinedButtonOptions = AppOutlinedButtonOptions(),
    content: @Composable RowScope.() -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val roleColor = if (options.danger) MaterialTheme.colorScheme.error else visuals.primary
    val borderColor by animateColorAsState(
        targetValue = roleColor.copy(
            alpha = if (pressed && options.enabled) ControlBorderPressedAlpha else ControlBorderIdleAlpha,
        ),
        label = "appOutlinedButtonBorder",
    )
    val containerColor by animateColorAsState(
        targetValue = if (pressed && options.enabled) {
            visuals.chipSelected.copy(alpha = ControlContainerPressedAlpha)
        } else {
            visuals.solidCard.copy(alpha = ControlContainerIdleAlpha)
        },
        label = "appOutlinedButtonContainer",
    )
    OutlinedButton(
        modifier = modifier.defaultMinSize(minHeight = AppSpacing.controlMinHeight),
        enabled = options.enabled,
        onClick = onClick,
        shape = RoundedCornerShape(AppRadius.small),
        interactionSource = interactionSource,
        contentPadding = options.contentPadding,
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = if (options.danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.48f),
            containerColor = containerColor,
            disabledContainerColor = visuals.solidCard.copy(alpha = 0.38f),
        ),
        border = BorderStroke(width = AppButtonTokens.BorderWidth, color = borderColor),
        content = content,
    )
}

private object AppButtonTokens {
    val BorderWidth = 1.dp
    val BackVisualSize = 34.dp
}
