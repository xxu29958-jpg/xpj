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
        AppSkin.Paper -> StateTokens(
            success = StateTone(Color(0xFFD9E0C4), Color(0xFF4F6B3A), Color(0xFFBCCAA6)),
            warn = StateTone(Color(0xFFF5E3C0), Color(0xFF7C4F0F), Color(0xFFE3CB91)),
            danger = StateTone(Color(0xFFF1D4CB), Color(0xFFA4361C), Color(0xFFE2B3A5)),
            info = StateTone(Color(0xFFDCE6E8), Color(0xFF3A5560), Color(0xFFBCCDD1)),
            neutral = StateTone(Color(0xFFECE7D8), Color(0xFF807968), Color(0xFFD6CFBE)),
        )
        AppSkin.Mono -> StateTokens(
            success = StateTone(Color(0xFFD6E2D6), Color(0xFF2C5036), Color(0xFFB7C9B8)),
            warn = StateTone(Color(0xFFE7DBC0), Color(0xFF665015), Color(0xFFD2C39A)),
            danger = StateTone(Color(0xFFF1D8D4), Color(0xFF8E1D12), Color(0xFFE2B9B3)),
            info = StateTone(Color(0xFFDBE1E3), Color(0xFF3A4A52), Color(0xFFBCC6CA)),
            neutral = StateTone(Color(0xFFE3E2DD), Color(0xFF3A3A37), Color(0xFFC9C8C3)),
        )
        AppSkin.Midnight -> StateTokens(
            success = StateTone(Color(0xFF1D2820), Color(0xFFA8B88A), Color(0xFF2E3D2A)),
            warn = StateTone(Color(0xFF2A241B), Color(0xFFD6B487), Color(0xFF3D3528)),
            danger = StateTone(Color(0xFF2A1E1B), Color(0xFFD97757), Color(0xFF3D2823)),
            info = StateTone(Color(0xFF1B2429), Color(0xFF84BCD4), Color(0xFF2A363D)),
            neutral = StateTone(Color(0xFF1C1F25), Color(0xFFB8B4A8), Color(0xFF2A2D35)),
        )
    }
}
