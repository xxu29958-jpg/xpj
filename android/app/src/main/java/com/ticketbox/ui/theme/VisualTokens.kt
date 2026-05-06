package com.ticketbox.ui.theme

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

data class ThemeVisuals(
    val primary: Color,
    val primaryDark: Color,
    val accent: Color,
    val backgroundTop: Color,
    val backgroundBottom: Color,
    val heroGradient: List<Color>,
    val glassTint: Color,
    val chipSelected: Color,
    val chipUnselected: Color,
    val shadowTint: Color,
    val illustrationTint: Color,
    val warmMist: Color,
    val coolMist: Color,
)

val LocalThemeVisuals = compositionLocalOf { themeVisualsForSkin(AppSkin.Default) }

fun themeVisualsForSkin(skin: AppSkin): ThemeVisuals {
    return when (skin) {
        AppSkin.Pine -> ThemeVisuals(
            primary = Color(0xFF185B4F),
            primaryDark = Color(0xFF0E433A),
            accent = Color(0xFFC8995F),
            backgroundTop = Color(0xFFF8F7EF),
            backgroundBottom = Color(0xFFE2EEE9),
            heroGradient = listOf(
                Color(0xFF185B4F),
                Color(0xFF2B7567),
                Color(0xFF0F443B),
            ),
            glassTint = Color(0xFFFFFCF4),
            chipSelected = Color(0xFFDDEBE5),
            chipUnselected = Color(0xFFF8FAF5),
            shadowTint = Color(0xFF476F64),
            illustrationTint = Color(0xFFD9CDBA),
            warmMist = Color(0xFFF1E2C9),
            coolMist = Color(0xFFA6C2B1),
        )
        AppSkin.Harbor -> ThemeVisuals(
            primary = Color(0xFF245D78),
            primaryDark = Color(0xFF16465E),
            accent = Color(0xFFD5A35D),
            backgroundTop = Color(0xFFFAF7EF),
            backgroundBottom = Color(0xFFD9EAF0),
            heroGradient = listOf(
                Color(0xFF245D78),
                Color(0xFF2F7B92),
                Color(0xFF185B4F),
            ),
            glassTint = Color(0xFFFFFCF5),
            chipSelected = Color(0xFFDCEAEF),
            chipUnselected = Color(0xFFF8FBFA),
            shadowTint = Color(0xFF406A78),
            illustrationTint = Color(0xFFD8C9AF),
            warmMist = Color(0xFFF0DDC0),
            coolMist = Color(0xFF9FC9D8),
        )
        AppSkin.Pomelo -> ThemeVisuals(
            primary = Color(0xFFE6981B),
            primaryDark = Color(0xFF9B6306),
            accent = Color(0xFF2D7A80),
            backgroundTop = Color(0xFFFFF8EA),
            backgroundBottom = Color(0xFFF1E6D0),
            heroGradient = listOf(
                Color(0xFFCE7F12),
                Color(0xFFE8A83F),
                Color(0xFF875C17),
            ),
            glassTint = Color(0xFFFFFCF5),
            chipSelected = Color(0xFFFFE7BB),
            chipUnselected = Color(0xFFFFFBF2),
            shadowTint = Color(0xFFB78331),
            illustrationTint = Color(0xFFE2C99E),
            warmMist = Color(0xFFFFD994),
            coolMist = Color(0xFFDCE8D9),
        )
        AppSkin.Berry -> ThemeVisuals(
            primary = Color(0xFFA83C5A),
            primaryDark = Color(0xFF7B2840),
            accent = Color(0xFF8B7A65),
            backgroundTop = Color(0xFFFFF4F7),
            backgroundBottom = Color(0xFFF0E7EB),
            heroGradient = listOf(
                Color(0xFFA83C5A),
                Color(0xFFC4657F),
                Color(0xFF743049),
            ),
            glassTint = Color(0xFFFFFAFC),
            chipSelected = Color(0xFFF2D7DF),
            chipUnselected = Color(0xFFFFF8FA),
            shadowTint = Color(0xFF9F6175),
            illustrationTint = Color(0xFFE3C7CF),
            warmMist = Color(0xFFF1D4C3),
            coolMist = Color(0xFFD7E4DD),
        )
        AppSkin.Night -> ThemeVisuals(
            primary = Color(0xFF2BB49A),
            primaryDark = Color(0xFF0A4139),
            accent = Color(0xFFD2A46E),
            backgroundTop = Color(0xFF041018),
            backgroundBottom = Color(0xFF0A2529),
            heroGradient = listOf(
                Color(0xFF0A4139),
                Color(0xFF174D52),
                Color(0xFF07151A),
            ),
            glassTint = Color(0xFF10262D),
            chipSelected = Color(0xFF163F3A),
            chipUnselected = Color(0xFF132A31),
            shadowTint = Color(0xFF061015),
            illustrationTint = Color(0xFF2B4F55),
            warmMist = Color(0xFF4D3617),
            coolMist = Color(0xFF2BB49A),
        )
    }
}
