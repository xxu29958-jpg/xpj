package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals

data class AppPrimaryNavItem(
    val key: String,
    val label: String,
    val icon: ImageVector,
)

/**
 * Primary navigation adapts to the available app window, not a device model.
 *
 * Compact-width windows use [AppBottomNav]. Medium and larger windows use this
 * Material 3 rail so split-screen, foldables, tablets, and desktop windowing do
 * not retain a phone-only bottom bar.
 */
@Composable
fun AppNavigationRail(
    items: List<AppPrimaryNavItem>,
    selectedKey: String,
    onSelect: (AppPrimaryNavItem) -> Unit,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    val haptics = rememberAppHaptics()
    Surface(
        modifier = modifier.fillMaxHeight(),
        color = visuals.surfaceNav.copy(alpha = AppAlpha.opaque),
    ) {
        Row {
            NavigationRail(
                modifier = Modifier.fillMaxHeight(),
                containerColor = Color.Transparent,
            ) {
                items.forEach { item ->
                    val selected = item.key == selectedKey
                    NavigationRailItem(
                        selected = selected,
                        onClick = {
                            if (!selected) haptics.tick()
                            onSelect(item)
                        },
                        icon = {
                            Icon(
                                imageVector = item.icon,
                                contentDescription = item.label,
                            )
                        },
                        label = {
                            Text(
                                text = item.label,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        },
                        alwaysShowLabel = true,
                    )
                }
            }
            VerticalDivider(
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.opaque),
            )
        }
    }
}

@Composable
fun AppBottomNav(
    items: List<AppPrimaryNavItem>,
    selectedKey: String,
    onSelect: (AppPrimaryNavItem) -> Unit,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    val haptics = rememberAppHaptics()
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .navigationBarsPadding(),
        color = visuals.surfaceNav.copy(alpha = AppAlpha.opaque),
        tonalElevation = 0.dp,
        shadowElevation = 0.dp,
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
        ) {
            HorizontalDivider(
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium),
            )
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = AppSpacing.miniGap,
                        vertical = AppSpacing.miniGap,
                    ),
                horizontalArrangement = Arrangement.Center,
            ) {
                items.forEach { item ->
                    val selected = item.key == selectedKey
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .heightIn(min = AppBottomNavLayout.ItemMinHeight)
                            .semantics {
                                role = Role.Button
                                this.selected = selected
                                contentDescription = item.label
                            }
                            .clickable(onClick = {
                                if (!selected) haptics.tick()
                                onSelect(item)
                            }),
                        contentAlignment = Alignment.Center,
                    ) {
                        AppBottomNavItemView(
                            item = item,
                            selected = selected,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun AppBottomNavItemView(
    item: AppPrimaryNavItem,
    selected: Boolean,
) {
    val visuals = LocalThemeVisuals.current
    // Warm Ledger 激活态：tonal pill 承载选中，而不是一条描边小指示线。
    val content = if (selected) {
        visuals.primary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(AppBottomNavLayout.ItemGap, Alignment.CenterVertically),
    ) {
        Box(
            modifier = Modifier
                .size(
                    width = AppBottomNavLayout.IndicatorWidth,
                    height = AppBottomNavLayout.IndicatorHeight,
                )
                .clip(CircleShape)
                .background(
                    color = if (selected) visuals.brandPrimaryBg else Color.Transparent,
                ),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = item.icon,
                contentDescription = null,
                tint = content,
                modifier = Modifier.size(AppBottomNavLayout.IconSize),
            )
        }
        Text(
            text = item.label,
            color = content,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = if (selected) AppTextHierarchy.heading.weight else AppTextHierarchy.caption.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

private object AppBottomNavLayout {
    val ItemMinHeight: Dp = AppSpacing.controlMinHeight
    val IndicatorWidth: Dp = 56.dp
    val IndicatorHeight: Dp = 28.dp
    val ItemGap: Dp = 3.dp
    val IconSize: Dp = 20.dp
}
