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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.AppTextHierarchy

private const val ControlBorderIdleAlpha = 0.28f
private const val ControlBorderPressedAlpha = 0.62f
private const val ControlContainerIdleAlpha = 0.62f
private const val ControlContainerPressedAlpha = 0.86f

@Composable
fun AppPrimaryButton(
    text: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.pill)
    Box(
        modifier = modifier
            .height(48.dp)
            .clip(shape)
            .background(
                Brush.horizontalGradient(
                    listOf(
                        visuals.primary.copy(alpha = 0.98f),
                        visuals.primaryDark.copy(alpha = 0.98f),
                    ),
                ),
            )
            .border(
                width = 1.dp,
                color = visuals.accent.copy(alpha = 0.34f),
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
                modifier = Modifier.size(20.dp),
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
    val shape = MaterialTheme.shapes.small
    Row(
        modifier = modifier
            .clearAndSetSemantics {
                contentDescription = text
                role = Role.Button
                onClick(action = {
                    onClick()
                    true
                })
            }
            .height(48.dp)
            .widthIn(min = 48.dp)
            .clip(shape)
            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.08f))
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.primary.copy(alpha = 0.12f),
                shape = shape,
            )
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = AppSpacing.compactGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(18.dp),
        )
        Text(
            text = text,
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
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
        modifier = modifier,
        enabled = enabled,
        onClick = onClick,
    ) {
        leadingIcon?.let {
            Icon(it, contentDescription = null, modifier = Modifier.size(18.dp))
            Box(modifier = Modifier.width(AppSpacing.smallGap))
        }
        Text(
            text = text,
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
    enabled: Boolean = true,
    danger: Boolean = false,
    contentPadding: PaddingValues = ButtonDefaults.ContentPadding,
    content: @Composable RowScope.() -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val roleColor = if (danger) MaterialTheme.colorScheme.error else visuals.primary
    val borderColor by animateColorAsState(
        targetValue = roleColor.copy(
            alpha = if (pressed && enabled) ControlBorderPressedAlpha else ControlBorderIdleAlpha,
        ),
        label = "appOutlinedButtonBorder",
    )
    val containerColor by animateColorAsState(
        targetValue = if (pressed && enabled) {
            visuals.chipSelected.copy(alpha = ControlContainerPressedAlpha)
        } else {
            visuals.solidCard.copy(alpha = ControlContainerIdleAlpha)
        },
        label = "appOutlinedButtonContainer",
    )
    OutlinedButton(
        modifier = modifier,
        enabled = enabled,
        onClick = onClick,
        interactionSource = interactionSource,
        contentPadding = contentPadding,
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.48f),
            containerColor = containerColor,
            disabledContainerColor = visuals.solidCard.copy(alpha = 0.38f),
        ),
        border = BorderStroke(width = 1.dp, color = borderColor),
        content = content,
    )
}

private fun Color.tonalDarken(multiplier: Float): Color {
    return Color(
        red = (red * multiplier).coerceIn(0f, 1f),
        green = (green * multiplier).coerceIn(0f, 1f),
        blue = (blue * multiplier).coerceIn(0f, 1f),
        alpha = alpha,
    )
}

private fun Color.blendTowards(target: Color, amount: Float): Color {
    val clamped = amount.coerceIn(0f, 1f)
    return Color(
        red = red + (target.red - red) * clamped,
        green = green + (target.green - green) * clamped,
        blue = blue + (target.blue - blue) * clamped,
        alpha = alpha + (target.alpha - alpha) * clamped,
    )
}
