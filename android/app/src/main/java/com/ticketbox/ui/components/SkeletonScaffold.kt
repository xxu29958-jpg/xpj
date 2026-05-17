package com.ticketbox.ui.components

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppSpacing
import com.valentinilk.shimmer.shimmer

/**
 * isLoading=true 时展示 skeleton 区域 (用 shimmer 包整个 area), 否则展示 content.
 * 取代旧 AppLoadingState 的进度条; SkeletonBlock 内部按 LocalSkeletonTokens 渲染色板.
 */
@Composable
fun SkeletonScaffold(
    isLoading: Boolean,
    modifier: Modifier = Modifier,
    skeleton: @Composable () -> Unit,
    content: @Composable () -> Unit,
) {
    AnimatedContent(
        targetState = isLoading,
        modifier = modifier,
        transitionSpec = {
            fadeIn(AppMotion.standardSpec(AppMotion.normalMillis))
                .togetherWith(fadeOut(AppMotion.exitSpec(AppMotion.fastMillis)))
        },
        label = "skeleton-scaffold",
    ) { loading ->
        if (loading) {
            Box(modifier = Modifier.fillMaxWidth().shimmer()) { skeleton() }
        } else { content() }
    }
}

@Composable
fun ListSkeletonPreset(
    rows: Int = 6,
    modifier: Modifier = Modifier,
    verticalSpacing: Dp = AppSpacing.smallGap,
) {
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(verticalSpacing)) {
        repeat(rows) { ListItemSkeleton() }
    }
}

@Composable
fun CardStackSkeletonPreset(
    cards: Int = 3,
    lines: Int = 3,
    modifier: Modifier = Modifier,
    verticalSpacing: Dp = AppSpacing.contentGap,
) {
    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(verticalSpacing)) {
        repeat(cards) { CardSkeleton(lines = lines) }
    }
}
