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
        confirm = SwipeAction(Color(0xFF176B5B), Color(0xFFFFFFFF), Color(0xFFFFFFFF)),
        ignore = SwipeAction(Color(0xFF66716B), Color(0xFFFFFFFF), Color(0xFFFFFFFF)),
        delete = SwipeAction(Color(0xFFA83D32), Color(0xFFFFFFFF), Color(0xFFFFFFFF)),
    )
    AppSkin.Midnight -> SwipeActionTokens(
        confirm = SwipeAction(Color(0xFF2C4B40), Color(0xFFB4E2D2), Color(0xFFB4E2D2)),
        ignore = SwipeAction(Color(0xFF303A35), Color(0xFFAAB5AF), Color(0xFFAAB5AF)),
        delete = SwipeAction(Color(0xFF4D302A), Color(0xFFF1A08E), Color(0xFFF1A08E)),
    )
}
