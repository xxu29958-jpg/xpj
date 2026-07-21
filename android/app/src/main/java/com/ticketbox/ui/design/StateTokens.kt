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
            success = StateTone(Color(0xFFE4F2EC), Color(0xFF236A57), Color(0xFFC8E2D8)),
            warn = StateTone(Color(0xFFF8EEDC), Color(0xFF8A5A18), Color(0xFFE6D2A9)),
            danger = StateTone(Color(0xFFF8E6E2), Color(0xFFA83D32), Color(0xFFEBC8C1)),
            info = StateTone(Color(0xFFE8EFF0), Color(0xFF49656B), Color(0xFFCFDDE0)),
            neutral = StateTone(Color(0xFFEDF1EE), Color(0xFF66716B), Color(0xFFDCE2DD)),
        )
        AppSkin.Mono -> StateTokens(
            success = StateTone(Color(0xFFE3EBE6), Color(0xFF315A45), Color(0xFFC6D5CB)),
            warn = StateTone(Color(0xFFF0E9DC), Color(0xFF6D5729), Color(0xFFDDD0B9)),
            danger = StateTone(Color(0xFFF1E2DF), Color(0xFF8C3B32), Color(0xFFDEC2BC)),
            info = StateTone(Color(0xFFE5EAEB), Color(0xFF485A5F), Color(0xFFCBD4D6)),
            neutral = StateTone(Color(0xFFE8ECE9), Color(0xFF626965), Color(0xFFD8DEDA)),
        )
        AppSkin.Midnight -> StateTokens(
            success = StateTone(Color(0xFF1C332B), Color(0xFF77C3A9), Color(0xFF2C4B40)),
            warn = StateTone(Color(0xFF332B20), Color(0xFFE3B36C), Color(0xFF4A3D2B)),
            danger = StateTone(Color(0xFF35231F), Color(0xFFE0836F), Color(0xFF4D302A)),
            info = StateTone(Color(0xFF1E2B2F), Color(0xFF8DB8C0), Color(0xFF2E4046)),
            neutral = StateTone(Color(0xFF1C2320), Color(0xFFAAB5AF), Color(0xFF303A35)),
        )
    }
}
