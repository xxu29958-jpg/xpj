package com.ticketbox.ui.design

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

/**
 * Skeleton 加载骨架 token，三端镜像 `shared/tokens.css` 的
 * `--skeleton-base-bg` / `--skeleton-shine-bg` / `--motion-shimmer`。
 *
 * 消费方：
 * - [base]：骨架块静止底色，[com.ticketbox.ui.components.SkeletonBlock] 默认色。
 * - [shine]：shimmer 扫光带色，`ui/theme/Theme.kt` 派生 `LocalShimmerTheme` 的渐变。
 * - [shimmerDurationMillis]：扫光周期（ms），同处派生 tween 时长；
 *   与 `--motion-shimmer: 1200ms` 等值，三端加载态节奏一致。
 */
data class SkeletonTokens(
    val base: Color,
    val shine: Color,
    val shimmerDurationMillis: Int = 1200,
)

val LocalSkeletonTokens = compositionLocalOf { skeletonTokensForSkin(AppSkin.Default) }

fun skeletonTokensForSkin(skin: AppSkin): SkeletonTokens = when (skin) {
    AppSkin.Paper -> SkeletonTokens(
        base = Color(0x141C1A18),
        shine = Color(0x33FFFFFF),
    )
    AppSkin.Mono -> SkeletonTokens(
        base = Color(0x140E0E0C),
        shine = Color(0x33FFFFFF),
    )
    AppSkin.Midnight -> SkeletonTokens(
        // Midnight 必须用暖金 alpha，否则 shimmer 在深色底上几乎不可见
        base = Color(0x0FD6B487),
        shine = Color(0x1FD6B487),
    )
}
