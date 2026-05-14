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
        AppSkin.Pine -> GoalTokens(
            idle = GoalStateTokens(Color(0xFFEFF1EC), Color(0xFF5C6760), Color(0xFFDDE2DA)),
            onTrack = GoalStateTokens(Color(0xFFE2EFE6), Color(0xFF1F6A45), Color(0xFFC4DECD)),
            nearLimit = GoalStateTokens(Color(0xFFF8E6C7), Color(0xFF8A5A12), Color(0xFFEAD5A2)),
            exceeded = GoalStateTokens(Color(0xFFF5D9D2), Color(0xFF8B3B34), Color(0xFFE8C0B5)),
            expired = GoalStateTokens(Color(0xFFE9EBE5), Color(0xFF7C857F), Color(0xFFD4D8D1)),
        )
        AppSkin.Pomelo -> GoalTokens(
            idle = GoalStateTokens(Color(0xFFF1E8D5), Color(0xFF6B5B3A), Color(0xFFE0D2B3)),
            onTrack = GoalStateTokens(Color(0xFFE3ECCF), Color(0xFF4F6B22), Color(0xFFCBD9AC)),
            nearLimit = GoalStateTokens(Color(0xFFFFE4B6), Color(0xFF8A5A12), Color(0xFFF1CE83)),
            exceeded = GoalStateTokens(Color(0xFFF6D6CB), Color(0xFF8B3B1F), Color(0xFFE9BBA8)),
            expired = GoalStateTokens(Color(0xFFEAE3D2), Color(0xFF8A7E5F), Color(0xFFD6CCB1)),
        )
        AppSkin.Harbor -> GoalTokens(
            idle = GoalStateTokens(Color(0xFFEDF2F3), Color(0xFF52646A), Color(0xFFD6DFE0)),
            onTrack = GoalStateTokens(Color(0xFFDCEFE3), Color(0xFF195039), Color(0xFFBADDC4)),
            nearLimit = GoalStateTokens(Color(0xFFF2E3CC), Color(0xFF7C4F0F), Color(0xFFE3CB9F)),
            exceeded = GoalStateTokens(Color(0xFFF5D6CD), Color(0xFF8B3B34), Color(0xFFE5B9AD)),
            expired = GoalStateTokens(Color(0xFFE7EBEC), Color(0xFF707F84), Color(0xFFCED7D8)),
        )
        AppSkin.Berry -> GoalTokens(
            idle = GoalStateTokens(Color(0xFFF0E7EB), Color(0xFF635458), Color(0xFFDED2D6)),
            onTrack = GoalStateTokens(Color(0xFFDDE8DD), Color(0xFF2F5D38), Color(0xFFBDD2BC)),
            nearLimit = GoalStateTokens(Color(0xFFF5DDC2), Color(0xFF8A5A1A), Color(0xFFE6C28E)),
            exceeded = GoalStateTokens(Color(0xFFF5D2DA), Color(0xFF7E1F36), Color(0xFFE8B0BC)),
            expired = GoalStateTokens(Color(0xFFE9E1E4), Color(0xFF837277), Color(0xFFD2C6CB)),
        )
        AppSkin.Night -> GoalTokens(
            idle = GoalStateTokens(Color(0xFF1A2A30), Color(0xFFB6C6C8), Color(0xFF243A42)),
            onTrack = GoalStateTokens(Color(0xFF11362F), Color(0xFF7CDDB8), Color(0xFF1A4A3E)),
            nearLimit = GoalStateTokens(Color(0xFF3A2A12), Color(0xFFE8C07A), Color(0xFF4E3919)),
            exceeded = GoalStateTokens(Color(0xFF3A1E1B), Color(0xFFEC9C8F), Color(0xFF4E2924)),
            expired = GoalStateTokens(Color(0xFF1D2A2E), Color(0xFF7B8B8C), Color(0xFF263740)),
        )
    }
}
