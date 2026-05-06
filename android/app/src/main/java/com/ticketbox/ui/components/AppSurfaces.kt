package com.ticketbox.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppElevation
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.theme.LocalThemeVisuals

@Composable
fun ScreenHeader(
    title: String,
    subtitle: String? = null,
    modifier: Modifier = Modifier,
    eyebrow: String = "小票夹",
    action: (@Composable RowScope.() -> Unit)? = null,
) {
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(
            text = eyebrow,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = FontWeight.Black,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Black,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                subtitle?.let {
                    Text(
                        text = it,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
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
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleLarge,
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = FontWeight.Black,
        )
        subtitle?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
fun SoftPanel(
    modifier: Modifier = Modifier,
    containerAlpha: Float = 0.64f,
    content: @Composable () -> Unit,
) {
    val resolvedAlpha = containerAlpha.coerceIn(0.78f, 1f)
    val shape = MaterialTheme.shapes.large
    Box(
        modifier = modifier
            .fillMaxWidth()
            .shadow(elevation = 14.dp, shape = shape, clip = false)
            .clip(shape)
            .background(
                Brush.verticalGradient(
                    listOf(
                        MaterialTheme.colorScheme.surface.copy(alpha = resolvedAlpha),
                        MaterialTheme.colorScheme.surface.copy(alpha = (resolvedAlpha * 0.94f).coerceIn(0.78f, 1f)),
                    ),
                ),
            )
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.48f),
                shape = shape,
            ),
    ) {
        content()
    }
}

@Composable
fun AppGlassCard(
    modifier: Modifier = Modifier,
    containerAlpha: Float = 0.90f,
    radius: RoundedCornerShape = RoundedCornerShape(AppRadius.large),
    content: @Composable () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val resolvedAlpha = containerAlpha.coerceIn(0.72f, 1f)
    Box(
        modifier = modifier
            .fillMaxWidth()
            .shadow(
                elevation = AppElevation.softCardShadow,
                shape = radius,
                clip = false,
                ambientColor = visuals.shadowTint.copy(alpha = 0.16f),
                spotColor = visuals.shadowTint.copy(alpha = 0.12f),
            )
            .clip(radius)
            .background(
                Brush.verticalGradient(
                    listOf(
                        visuals.glassTint.copy(alpha = resolvedAlpha),
                        MaterialTheme.colorScheme.surface.copy(alpha = (resolvedAlpha * 0.96f).coerceIn(0.74f, 1f)),
                    ),
                ),
            )
            .border(
                width = 1.dp,
                color = Color.White.copy(alpha = if (MaterialTheme.colorScheme.background.luminance() > 0.5f) 0.66f else 0.14f),
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
    AppGlassCard(
        modifier = modifier,
        containerAlpha = 0.98f,
        radius = RoundedCornerShape(AppRadius.large),
        content = content,
    )
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
            .shadow(
                elevation = AppElevation.heroShadow,
                shape = shape,
                clip = false,
                ambientColor = visuals.shadowTint.copy(alpha = 0.22f),
                spotColor = visuals.shadowTint.copy(alpha = 0.16f),
            )
            .clip(shape)
            .background(Brush.linearGradient(visuals.heroGradient))
            .border(
                width = 1.dp,
                color = Color.White.copy(alpha = 0.20f),
                shape = shape,
            ),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.radialGradient(
                        listOf(
                            Color.White.copy(alpha = 0.18f),
                            Color.Transparent,
                        ),
                    ),
                ),
        )
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        listOf(
                            Color.White.copy(alpha = 0.08f),
                            Color.Transparent,
                            Color.Black.copy(alpha = 0.10f),
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
    val shape = RoundedCornerShape(999.dp)
    Box(
        modifier = modifier
            .height(60.dp)
            .shadow(
                elevation = if (enabled) 16.dp else 0.dp,
                shape = shape,
                clip = false,
                ambientColor = visuals.shadowTint.copy(alpha = 0.22f),
                spotColor = visuals.shadowTint.copy(alpha = 0.16f),
            )
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
                color = Color.White.copy(alpha = 0.26f),
                shape = shape,
            )
            .alpha(if (enabled) 1f else 0.58f)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        listOf(
                            Color.White.copy(alpha = 0.16f),
                            Color.Transparent,
                            Color.Black.copy(alpha = 0.08f),
                        ),
                    ),
                ),
        )
        Row(
            horizontalArrangement = Arrangement.spacedBy(9.dp),
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
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Black,
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
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
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
            .clip(CircleShape)
            .background(
                if (active) {
                    MaterialTheme.colorScheme.primaryContainer
                } else {
                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.70f)
                },
            )
            .padding(horizontal = 13.dp, vertical = 7.dp),
        color = if (active) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.Bold,
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
            Box(modifier = Modifier.width(8.dp))
        }
        Text(text)
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
            .padding(horizontal = 14.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
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
    Box(
        modifier = modifier
            .size(width = width, height = height)
            .clip(MaterialTheme.shapes.medium)
            .background(
                Brush.verticalGradient(
                    listOf(
                        Color(0xFFFFFBF3),
                        Color(0xFFF1E9DB),
                    ),
                ),
            )
            .border(1.dp, Color(0xFFE2D8C8), MaterialTheme.shapes.medium)
            .padding(horizontal = 14.dp, vertical = 14.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(if (compact) 8.dp else 11.dp)) {
            repeat(if (compact) 4 else 7) { index ->
                Box(
                    modifier = Modifier
                        .width(if (index % 3 == 0) width - 34.dp else width - 48.dp)
                        .height(3.dp)
                        .clip(CircleShape)
                        .background(Color(0xFFBDB7AB)),
                )
            }
        }
        Box(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth(0.72f)
                .height(14.dp)
                .clip(CircleShape)
                .background(Color(0xFFE0D5C4)),
        )
    }
}

private fun Color.luminance(): Float {
    return red * 0.299f + green * 0.587f + blue * 0.114f
}
