package com.ticketbox.ui.design

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

data class GoalStateTokens(
    val bg: Color,
    val fg: Color,
    val border: Color,
)

data class GoalTokens(
    val idle: GoalStateTokens,
    val onTrack: GoalStateTokens,
    val nearLimit: GoalStateTokens,
    val exceeded: GoalStateTokens,
    val expired: GoalStateTokens,
)

val LocalGoalTokens = compositionLocalOf { goalTokensForSkin(AppSkin.Default) }

fun goalTokensForSkin(skin: AppSkin): GoalTokens {
    return when (skin) {
        AppSkin.Paper -> GoalTokens(
            idle = GoalStateTokens(Color(0xFFEDF1EE), Color(0xFF66716B), Color(0xFFDCE2DD)),
            onTrack = GoalStateTokens(Color(0xFFE1F0EA), Color(0xFF176B5B), Color(0xFFC5DED5)),
            nearLimit = GoalStateTokens(Color(0xFFF8EEDC), Color(0xFF8A5A18), Color(0xFFE6D2A9)),
            exceeded = GoalStateTokens(Color(0xFFF8E6E2), Color(0xFFA83D32), Color(0xFFEBC8C1)),
            expired = GoalStateTokens(Color(0xFFE9EDEA), Color(0xFF7A847E), Color(0xFFD8DEDA)),
        )
        AppSkin.Midnight -> GoalTokens(
            idle = GoalStateTokens(Color(0xFF1C2320), Color(0xFFAAB5AF), Color(0xFF303A35)),
            onTrack = GoalStateTokens(Color(0xFF1C332B), Color(0xFF77C3A9), Color(0xFF2C4B40)),
            nearLimit = GoalStateTokens(Color(0xFF332B20), Color(0xFFE3B36C), Color(0xFF4A3D2B)),
            exceeded = GoalStateTokens(Color(0xFF35231F), Color(0xFFE0836F), Color(0xFF4D302A)),
            expired = GoalStateTokens(Color(0xFF1B211E), Color(0xFF77837D), Color(0xFF2C3530)),
        )
    }
}
