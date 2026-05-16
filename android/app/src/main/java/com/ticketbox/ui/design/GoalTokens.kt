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
            idle = GoalStateTokens(Color(0xFFECE7D8), Color(0xFF807968), Color(0xFFD6CFBE)),
            onTrack = GoalStateTokens(Color(0xFFD9E0C4), Color(0xFF4F6B3A), Color(0xFFBCCAA6)),
            nearLimit = GoalStateTokens(Color(0xFFF5E3C0), Color(0xFF7C4F0F), Color(0xFFE3CB91)),
            exceeded = GoalStateTokens(Color(0xFFF1D4CB), Color(0xFFA4361C), Color(0xFFE2B3A5)),
            expired = GoalStateTokens(Color(0xFFE9E5D9), Color(0xFF8A8478), Color(0xFFD2CCBD)),
        )
        AppSkin.Mono -> GoalTokens(
            idle = GoalStateTokens(Color(0xFFE3E2DD), Color(0xFF3A3A37), Color(0xFFC9C8C3)),
            onTrack = GoalStateTokens(Color(0xFFD6E2D6), Color(0xFF2C5036), Color(0xFFB7C9B8)),
            nearLimit = GoalStateTokens(Color(0xFFE7DBC0), Color(0xFF665015), Color(0xFFD2C39A)),
            exceeded = GoalStateTokens(Color(0xFFF1D8D4), Color(0xFF8E1D12), Color(0xFFE2B9B3)),
            expired = GoalStateTokens(Color(0xFFE7E6E1), Color(0xFF6F6E6A), Color(0xFFCDCDC8)),
        )
        AppSkin.Midnight -> GoalTokens(
            idle = GoalStateTokens(Color(0xFF1C1F25), Color(0xFFB8B4A8), Color(0xFF2A2D35)),
            onTrack = GoalStateTokens(Color(0xFF1D2820), Color(0xFFA8B88A), Color(0xFF2E3D2A)),
            nearLimit = GoalStateTokens(Color(0xFF2A241B), Color(0xFFD6B487), Color(0xFF3D3528)),
            exceeded = GoalStateTokens(Color(0xFF2A1E1B), Color(0xFFD97757), Color(0xFF3D2823)),
            expired = GoalStateTokens(Color(0xFF1D2025), Color(0xFF807C70), Color(0xFF2C2F37)),
        )
    }
}
