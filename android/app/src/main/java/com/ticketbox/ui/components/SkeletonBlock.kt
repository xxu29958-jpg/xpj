package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.valentinilk.shimmer.shimmer

/**
 * 通用 shimmer 占位"骨架"块。
 *
 * 用法：用 [Column].[shimmer] 包住一段 layout，里面用 [SkeletonBlock] 填充
 * 形状（圆/矩形/圆角条），整体会有左右流动的微光效果。
 *
 * 设计取舍：
 * - 不在内部 wrap [shimmer]——shimmer 应该一次包整个骨架区域，
 *   而不是每个 SkeletonBlock 各跑一次动画（会出现不同步抖动）。
 * - 颜色用 onSurface.copy(alpha=0.08)，在 paper/mono/midnight 三套主题下
 *   都能提供"显然这是占位"的视觉量。
 */
@Composable
fun SkeletonBlock(
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(AppRadius.extraSmall),
    color: Color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f),
) {
    Box(
        modifier = modifier
            .clip(shape)
            .background(color),
    )
}

/**
 * 列表项骨架：圆形分类标记 + 双行文本 + 右侧金额条。
 *
 * 对应 Ledger / Pending / Recurring 等列表类页面的加载态。
 * 调用方负责用 [shimmer] 包整个父布局：
 *
 * ```
 * Column(modifier = Modifier.shimmer()) {
 *     repeat(8) { ListItemSkeleton() }
 * }
 * ```
 */
@Composable
fun ListItemSkeleton(
    modifier: Modifier = Modifier,
    horizontalPadding: Dp = AppSpacing.screenHorizontal,
    verticalPadding: Dp = AppSpacing.contentGap,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = horizontalPadding, vertical = verticalPadding),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SkeletonBlock(
            modifier = Modifier.size(36.dp),
            shape = CircleShape,
        )
        Spacer(modifier = Modifier.width(AppSpacing.contentGap))
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            SkeletonBlock(
                modifier = Modifier.fillMaxWidth(fraction = 0.55f).height(14.dp),
            )
            SkeletonBlock(
                modifier = Modifier.fillMaxWidth(fraction = 0.32f).height(10.dp),
            )
        }
        Spacer(modifier = Modifier.width(AppSpacing.contentGap))
        SkeletonBlock(
            modifier = Modifier.width(64.dp).height(16.dp),
        )
    }
}

/**
 * 卡片骨架：卡片标题条 + 多行内容条。
 *
 * 用于 Stats / Dashboard 类卡片堆叠的页面加载态。
 */
@Composable
fun CardSkeleton(
    modifier: Modifier = Modifier,
    lines: Int = 3,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(AppRadius.medium))
            .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.6f))
            .padding(AppSpacing.cardPaddingSmall),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        // Title bar
        SkeletonBlock(
            modifier = Modifier.fillMaxWidth(fraction = 0.4f).height(18.dp),
        )
        Spacer(modifier = Modifier.height(2.dp))
        // Hero number (amount placeholder)
        SkeletonBlock(
            modifier = Modifier.fillMaxWidth(fraction = 0.6f).height(28.dp),
        )
        // Content lines
        repeat(lines) {
            SkeletonBlock(
                modifier = Modifier.fillMaxWidth(fraction = (0.5f + it * 0.12f).coerceAtMost(0.95f)).height(12.dp),
            )
        }
    }
}
