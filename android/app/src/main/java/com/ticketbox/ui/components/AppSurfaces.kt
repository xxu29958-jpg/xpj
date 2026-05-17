package com.ticketbox.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
fun ScreenHeader(
    title: String,
    subtitle: String? = null,
    modifier: Modifier = Modifier,
    eyebrow: String = "小票夹",
    action: (@Composable RowScope.() -> Unit)? = null,
) {
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        if (eyebrow.isNotBlank()) {
            Text(
                text = eyebrow,
                style = MaterialTheme.typography.titleMedium.copy(
                    fontSize = AppTypography.appLabel.size,
                    lineHeight = 20.sp,
                    letterSpacing = 0.06.sp,
                ),
                color = MaterialTheme.colorScheme.onBackground,
                fontWeight = AppTypography.appLabel.weight,
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleLarge.copy(
                        fontSize = AppTypography.pageTitle.size,
                        lineHeight = 34.sp,
                        letterSpacing = 0.sp,
                    ),
                    fontWeight = AppTypography.pageTitle.weight,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                subtitle?.let {
                    Text(
                        text = it,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium.copy(
                            fontSize = AppTypography.body.size,
                            lineHeight = 22.sp,
                        ),
                    )
                }
            }
            action?.invoke(this)
        }
    }
}

@Composable
fun SectionTitle(
    title: String,
    subtitle: String? = null,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleLarge.copy(
                fontSize = AppTypography.sectionTitle.size,
                lineHeight = 26.sp,
                letterSpacing = 0.sp,
            ),
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = AppTypography.sectionTitle.weight,
        )
        subtitle?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium.copy(
                    fontSize = AppTypography.body.size,
                    lineHeight = 22.sp,
                ),
            )
        }
    }
}

@Composable
fun AppGlassCard(
    modifier: Modifier = Modifier,
    containerAlpha: Float = 0.96f,
    radius: RoundedCornerShape = RoundedCornerShape(AppRadius.large),
    content: @Composable () -> Unit,
) {
    val resolvedAlpha = containerAlpha.coerceIn(0.88f, 1f)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(radius)
            .background(
                Brush.verticalGradient(
                    listOf(
                        MaterialTheme.colorScheme.surface.copy(alpha = resolvedAlpha),
                        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = (resolvedAlpha * 0.52f).coerceIn(0.42f, 0.78f)),
                    ),
                ),
            )
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.72f),
                shape = radius,
            ),
    ) {
        content()
    }
}

@Composable
fun AppSolidCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    // Solid cards are for edit, settings, and other input-heavy surfaces that
    // need stronger separation from the immersive background.
    AppGlassCard(
        modifier = modifier,
        containerAlpha = 0.98f,
        radius = RoundedCornerShape(AppRadius.large),
        content = content,
    )
}

@Composable
fun AppContentCard(
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(AppSpacing.cardPadding),
    verticalArrangement: Arrangement.Vertical = Arrangement.spacedBy(AppSpacing.contentGap),
    content: @Composable ColumnScope.() -> Unit,
) {
    AppSolidCard(modifier = modifier) {
        Column(
            modifier = Modifier.padding(contentPadding),
            verticalArrangement = verticalArrangement,
            content = content,
        )
    }
}

@Composable
fun AppEmptyStateCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    AppGlassCard(
        modifier = modifier,
        containerAlpha = 0.94f,
        radius = RoundedCornerShape(AppRadius.large),
        content = content,
    )
}

@Composable
fun AppHeroCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.hero)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(shape)
            .background(
                Brush.horizontalGradient(
                    listOf(
                        visuals.primary,
                        visuals.primaryDark,
                    ),
                ),
            )
            .border(
                width = 1.dp,
                color = visuals.accent.copy(alpha = 0.42f),
                shape = shape,
            ),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        listOf(
                            Color.White.copy(alpha = 0.10f),
                            Color.Transparent,
                            Color.Black.copy(alpha = 0.08f),
                        ),
                    ),
                ),
        )
        content()
    }
}

@Composable
fun DeepHeroPanel(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    AppHeroCard(modifier = modifier, content = content)
}

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
                fontWeight = FontWeight.Black,
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

@Composable
fun MetricTile(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    tint: Color = MaterialTheme.colorScheme.primary,
) {
    Column(
        modifier = modifier
            .clip(MaterialTheme.shapes.medium)
            .background(MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.72f))
            .padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.compactGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(
            text = value,
            color = tint,
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Black,
        )
    }
}

@Composable
fun StatusPill(
    text: String,
    modifier: Modifier = Modifier,
    active: Boolean = true,
) {
    Text(
        text = text,
        modifier = modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(
                if (active) {
                    MaterialTheme.colorScheme.primaryContainer
                } else {
                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.70f)
                },
            )
            .padding(horizontal = AppSpacing.compactGap, vertical = AppSpacing.smallGap),
        color = if (active) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.Bold,
    )
}

@Composable
fun AppSwitch(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val visuals = LocalThemeVisuals.current
    Switch(
        checked = checked,
        onCheckedChange = onCheckedChange,
        enabled = enabled,
        modifier = modifier,
        colors = SwitchDefaults.colors(
            checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
            checkedTrackColor = visuals.primary.copy(alpha = 0.92f),
            checkedBorderColor = visuals.primary.copy(alpha = 0.80f),
            uncheckedThumbColor = MaterialTheme.colorScheme.onSurfaceVariant,
            uncheckedTrackColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.74f),
            uncheckedBorderColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.62f),
            disabledCheckedThumbColor = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.58f),
            disabledCheckedTrackColor = visuals.primary.copy(alpha = 0.36f),
            disabledUncheckedThumbColor = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.42f),
            disabledUncheckedTrackColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.44f),
        ),
    )
}

@Composable
fun QuietOutlinedButton(
    text: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    leadingIcon: ImageVector? = null,
    onClick: () -> Unit,
) {
    OutlinedButton(
        modifier = modifier,
        enabled = enabled,
        onClick = onClick,
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = MaterialTheme.colorScheme.onSurface,
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.62f),
        ),
        border = BorderStroke(
            width = 1.dp,
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.42f),
        ),
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
fun SafeBadge(
    modifier: Modifier = Modifier,
    text: String = "安全",
) {
    StatusPill(text = text, modifier = modifier, active = true)
}

@Composable
fun IconChip(
    icon: ImageVector,
    label: String,
    modifier: Modifier = Modifier,
    selected: Boolean = false,
) {
    Row(
        modifier = modifier
            .clip(CircleShape)
            .background(
                if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface,
            )
            .padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.contentGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(18.dp),
        )
        Text(
            text = label,
            color = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
fun ReceiptStub(
    modifier: Modifier = Modifier,
    compact: Boolean = false,
) {
    val width = if (compact) 76.dp else 110.dp
    val height = if (compact) 92.dp else 132.dp
    val palette = LocalThemeVisuals.current.receiptStub
    Box(
        modifier = modifier
            .size(width = width, height = height)
            .clip(MaterialTheme.shapes.medium)
            .background(
                Brush.verticalGradient(
                    listOf(palette.paperTop, palette.paperBottom),
                ),
            )
            .border(1.dp, palette.border, MaterialTheme.shapes.medium)
            .padding(horizontal = 14.dp, vertical = 14.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(if (compact) 8.dp else 11.dp)) {
            repeat(if (compact) 4 else 7) { index ->
                Box(
                    modifier = Modifier
                        .width(if (index % 3 == 0) width - 34.dp else width - 48.dp)
                        .height(3.dp)
                        .clip(CircleShape)
                        .background(palette.line),
                )
            }
        }
        Box(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth(0.72f)
                .height(14.dp)
                .clip(CircleShape)
                .background(palette.stripe),
        )
    }
}

private fun Color.luminance(): Float {
    return red * 0.299f + green * 0.587f + blue * 0.114f
}
