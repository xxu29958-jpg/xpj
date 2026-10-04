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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals

private const val ControlBorderIdleAlpha = 0.46f
private const val ControlBorderPressedAlpha = 0.82f
private const val ControlContainerIdleAlpha = 0.98f
private const val ControlContainerPressedAlpha = 1f
private const val PrimaryDisabledContentAlpha = 0.58f

data class AppButtonIcons(
    val leading: ImageVector? = null,
    val trailing: ImageVector? = null,
)

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
    icons: AppButtonIcons = AppButtonIcons(),
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.medium)
    // 禁用淡化走内容色级 alpha，不用 Modifier.alpha：后者在 disabled→enabled 翻转时会摘除
    // 链上的 graphicsLayer 元素（结构手术），eb49 实机曾因此永久丢失外侧 background/border
    // 绘制（合同回归见 AppPrimaryButtonRenderTest）。盒体填充两态均为满色，视觉不变。
    val contentColor = MaterialTheme.colorScheme.onPrimary.copy(
        alpha = if (enabled) 1f else PrimaryDisabledContentAlpha,
    )
    Box(
        modifier = modifier
            .heightIn(min = AppSpacing.controlMinHeight + AppSpacing.miniGap)
            .clip(shape)
            .background(visuals.primary)
            .border(
                width = AppButtonTokens.BorderWidth,
                color = visuals.primaryDark.copy(alpha = 0.74f),
                shape = shape,
            )
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = AppSpacing.compactGap, vertical = AppSpacing.smallGap),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            icons.leading?.let {
                Icon(
                    imageVector = it,
                    contentDescription = null,
                    tint = contentColor,
                    modifier = Modifier.size(AppIconSize.standard),
                )
            }
            Text(
                text = text,
                color = contentColor,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = AppTextHierarchy.heading.weight,
                textAlign = TextAlign.Center,
                modifier = Modifier.weight(1f, fill = false),
            )
            icons.trailing?.let {
                Icon(it, contentDescription = null, tint = contentColor, modifier = Modifier.size(AppIconSize.standard))
            }
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
    AppPrimaryButton(text = text, icons = AppButtonIcons(leading = icon), modifier = modifier, enabled = enabled, onClick = onClick)
}

@Composable
fun AppBackButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    TextButton(
        modifier = modifier
            .heightIn(min = AppSpacing.controlMinHeight)
            .semantics { contentDescription = text },
        onClick = onClick,
    ) {
        Icon(ImageVector.vectorResource(R.drawable.ic_lucide_arrow_left), contentDescription = null)
        Spacer(Modifier.width(AppSpacing.smallGap))
        Text(text)
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
        shape = RoundedCornerShape(AppRadius.medium),
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
}
