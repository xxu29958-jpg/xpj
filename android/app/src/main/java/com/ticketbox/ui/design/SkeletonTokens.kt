package com.ticketbox.ui.design

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

data class SkeletonTokens(
    val base: Color,
    val shine: Color,
    val shimmerDurationMillis: Int = 1400,
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
