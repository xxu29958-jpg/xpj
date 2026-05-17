package com.ticketbox.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.expandHorizontally
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals

data class AppBottomNavItem(
    val key: String,
    val label: String,
    val icon: ImageVector,
)

@Composable
fun AppBottomNav(
    items: List<AppBottomNavItem>,
    selectedKey: String,
    onSelect: (AppBottomNavItem) -> Unit,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    val haptics = rememberAppHaptics()
    Box(
        modifier = modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(
                start = AppBottomNavLayout.OuterHorizontalPadding,
                end = AppBottomNavLayout.OuterHorizontalPadding,
                top = AppSpacing.smallGap,
                bottom = AppSpacing.smallGap,
            ),
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(AppRadius.bottomBar),
            color = visuals.solidCard.copy(alpha = 0.995f),
            tonalElevation = 0.dp,
            shadowElevation = 0.dp,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(
                        horizontal = AppSpacing.compactPadding,
                        vertical = AppBottomNavLayout.InnerVerticalPadding,
                    ),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                items.forEach { item ->
                    val selected = item.key == selectedKey
                    Box(
                        modifier = Modifier
                            .weight(if (selected) AppBottomNavLayout.SelectedWeight else 1f)
                            .height(AppBottomNavLayout.ItemHeight)
                            // Role.Tab + selected 让 TalkBack 念出 "已选中 / 共 N 项 / 当前是第 X 项"
                            .semantics {
                                role = Role.Tab
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
    item: AppBottomNavItem,
    selected: Boolean,
) {
    val visuals = LocalThemeVisuals.current
    val background by animateColorAsState(
        targetValue = if (selected) visuals.primary.copy(alpha = 0.90f) else Color.Transparent,
        label = "appBottomNavBackground",
    )
    val content by animateColorAsState(
        targetValue = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
        label = "appBottomNavContent",
    )

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(AppBottomNavLayout.PillHeight)
            .clip(RoundedCornerShape(AppRadius.large))
            .background(background)
            .padding(horizontal = AppSpacing.smallGap, vertical = AppBottomNavLayout.PillVerticalPadding),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = item.icon,
            contentDescription = item.label,
            tint = content,
            modifier = Modifier.size(AppBottomNavLayout.IconSize),
        )
        AnimatedVisibility(
            visible = selected,
            enter = fadeIn(tween(AppMotion.fastMillis)) + expandHorizontally(tween(AppMotion.fastMillis)),
            exit = fadeOut(tween(AppMotion.fastMillis)) + shrinkHorizontally(tween(AppMotion.fastMillis)),
        ) {
            Text(
                text = item.label,
                color = content,
                style = MaterialTheme.typography.labelSmall.copy(
                    fontSize = 12.sp,
                    lineHeight = 15.sp,
                ),
                fontWeight = AppTextHierarchy.heading.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

private object AppBottomNavLayout {
    val OuterHorizontalPadding: Dp = 16.dp
    val InnerVerticalPadding: Dp = 6.dp
    val ItemHeight: Dp = 48.dp
    val PillHeight: Dp = 40.dp
    val PillVerticalPadding: Dp = 6.dp
    val IconSize: Dp = 17.dp
    const val SelectedWeight: Float = 1.14f
}
