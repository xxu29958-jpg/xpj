package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

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
        fontWeight = AppTextHierarchy.body.weight,
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
fun SafeBadge(
    modifier: Modifier = Modifier,
    text: String = stringResource(R.string.components_safe_badge_label),
) {
    StatusPill(text = text, modifier = modifier, active = true)
}

/**
 * 计数 badge：镜像 /web 的 `.nav-badge`（pill、brand 主色容器底 + 主色字、等宽数字、紧凑），用于
 * 菜单项/导航项的待办计数（如统计页头「管理」菜单的「还款待确认」项 = pending 还款草稿数）。三端共用
 * 一套设计语言（brand 主色容器），不分叉。
 *
 * 调用方负责「>0 才显示」的判定（与 /web `{% if pending_count %}` 一致）；[contentDescription] 给定时整个
 * badge 作为单个无障碍节点朗读该描述（如「3 笔待复核」），替代裸数字「3」。
 */
@Composable
fun CountBadge(
    count: Int,
    modifier: Modifier = Modifier,
    contentDescription: String? = null,
) {
    Text(
        text = count.toString(),
        modifier = modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(MaterialTheme.colorScheme.primaryContainer)
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap)
            .then(
                if (contentDescription != null) {
                    Modifier.clearAndSetSemantics { this.contentDescription = contentDescription }
                } else {
                    Modifier
                },
            ),
        color = MaterialTheme.colorScheme.primary,
        style = MaterialTheme.typography.labelMedium.tabularNum(),
        fontWeight = AppTextHierarchy.body.weight,
    )
}
