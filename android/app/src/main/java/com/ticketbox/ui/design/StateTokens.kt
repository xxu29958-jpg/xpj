package com.ticketbox.ui.design

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

data class StateTone(
    val bg: Color,
    val fg: Color,
    val border: Color,
)

data class StateTokens(
    val success: StateTone,
    val warn: StateTone,
    val danger: StateTone,
    val info: StateTone,
    val neutral: StateTone,
)

val LocalStateTokens = compositionLocalOf { stateTokensForSkin(AppSkin.Default) }

fun stateTokensForSkin(skin: AppSkin): StateTokens {
    return when (skin) {
        AppSkin.Pine -> StateTokens(
            success = StateTone(Color(0xFFE2EFE6), Color(0xFF1F6A45), Color(0xFFC4DECD)),
            warn = StateTone(Color(0xFFF8E6C7), Color(0xFF8A5A12), Color(0xFFEAD5A2)),
            danger = StateTone(Color(0xFFF5D9D2), Color(0xFF8B3B34), Color(0xFFE8C0B5)),
            info = StateTone(Color(0xFFDDEBE5), Color(0xFF1F4D45), Color(0xFFC4D9D0)),
            neutral = StateTone(Color(0xFFEFF1EC), Color(0xFF5C6760), Color(0xFFDDE2DA)),
        )
        AppSkin.Pomelo -> StateTokens(
            success = StateTone(Color(0xFFE3ECCF), Color(0xFF4F6B22), Color(0xFFCBD9AC)),
            warn = StateTone(Color(0xFFFFE4B6), Color(0xFF8A5A12), Color(0xFFF1CE83)),
            danger = StateTone(Color(0xFFF6D6CB), Color(0xFF8B3B1F), Color(0xFFE9BBA8)),
            info = StateTone(Color(0xFFDDEEEF), Color(0xFF195059), Color(0xFFBED9DC)),
            neutral = StateTone(Color(0xFFF1E8D5), Color(0xFF6B5B3A), Color(0xFFE0D2B3)),
        )
        AppSkin.Harbor -> StateTokens(
            success = StateTone(Color(0xFFDCEFE3), Color(0xFF195039), Color(0xFFBADDC4)),
            warn = StateTone(Color(0xFFF2E3CC), Color(0xFF7C4F0F), Color(0xFFE3CB9F)),
            danger = StateTone(Color(0xFFF5D6CD), Color(0xFF8B3B34), Color(0xFFE5B9AD)),
            info = StateTone(Color(0xFFDDEAF0), Color(0xFF124360), Color(0xFFBCD5E2)),
            neutral = StateTone(Color(0xFFEDF2F3), Color(0xFF52646A), Color(0xFFD6DFE0)),
        )
        AppSkin.Berry -> StateTokens(
            success = StateTone(Color(0xFFDDE8DD), Color(0xFF2F5D38), Color(0xFFBDD2BC)),
            warn = StateTone(Color(0xFFF5DDC2), Color(0xFF8A5A1A), Color(0xFFE6C28E)),
            danger = StateTone(Color(0xFFF5D2DA), Color(0xFF7E1F36), Color(0xFFE8B0BC)),
            info = StateTone(Color(0xFFE6DDE9), Color(0xFF513363), Color(0xFFCEBFD6)),
            neutral = StateTone(Color(0xFFF0E7EB), Color(0xFF635458), Color(0xFFDED2D6)),
        )
        AppSkin.Night -> StateTokens(
            success = StateTone(Color(0xFF11362F), Color(0xFF7CDDB8), Color(0xFF1A4A3E)),
            warn = StateTone(Color(0xFF3A2A12), Color(0xFFE8C07A), Color(0xFF4E3919)),
            danger = StateTone(Color(0xFF3A1E1B), Color(0xFFEC9C8F), Color(0xFF4E2924)),
            info = StateTone(Color(0xFF12303D), Color(0xFF84BCD4), Color(0xFF1B4255)),
            neutral = StateTone(Color(0xFF1A2A30), Color(0xFFB6C6C8), Color(0xFF243A42)),
        )
    }
}
