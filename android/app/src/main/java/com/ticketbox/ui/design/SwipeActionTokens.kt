package com.ticketbox.ui.design

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

data class SwipeAction(
    val bg: Color,
    val fg: Color,
    val iconTint: Color,
)

data class SwipeActionTokens(
    val confirm: SwipeAction,
    val ignore: SwipeAction,
    val delete: SwipeAction,
)

val LocalSwipeActionTokens = compositionLocalOf { swipeActionTokensForSkin(AppSkin.Default) }

fun swipeActionTokensForSkin(skin: AppSkin): SwipeActionTokens = when (skin) {
    AppSkin.Paper -> SwipeActionTokens(
        confirm = SwipeAction(Color(0xFF4F6B3A), Color(0xFFFBF8F1), Color(0xFFFBF8F1)),
        ignore = SwipeAction(Color(0xFF807968), Color(0xFFFBF8F1), Color(0xFFFBF8F1)),
        delete = SwipeAction(Color(0xFFA4361C), Color(0xFFFBF8F1), Color(0xFFFBF8F1)),
    )
    AppSkin.Mono -> SwipeActionTokens(
        confirm = SwipeAction(Color(0xFF2C5036), Color(0xFFFAFAF8), Color(0xFFFAFAF8)),
        ignore = SwipeAction(Color(0xFF6F6E6A), Color(0xFFFAFAF8), Color(0xFFFAFAF8)),
        delete = SwipeAction(Color(0xFF8E1D12), Color(0xFFFAFAF8), Color(0xFFFAFAF8)),
    )
    AppSkin.Midnight -> SwipeActionTokens(
        confirm = SwipeAction(Color(0xFF2E3D2A), Color(0xFFA8B88A), Color(0xFFA8B88A)),
        ignore = SwipeAction(Color(0xFF2A2D35), Color(0xFFB8B4A8), Color(0xFFB8B4A8)),
        delete = SwipeAction(Color(0xFF3D2823), Color(0xFFD97757), Color(0xFFD97757)),
    )
}
