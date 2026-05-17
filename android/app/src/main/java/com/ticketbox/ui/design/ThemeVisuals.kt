package com.ticketbox.ui.design

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

data class ReceiptStubPalette(
    val paperTop: Color,
    val paperBottom: Color,
    val border: Color,
    val line: Color,
    val footer: Color,
)

data class ThemeVisuals(
    val primary: Color,
    val primaryDark: Color,
    val accent: Color,
    val backgroundTop: Color,
    val backgroundBottom: Color,
    val heroGradient: List<Color>,
    val heroGradientStart: Color,
    val heroGradientEnd: Color,
    val heroGlow: Color,
    val glassTint: Color,
    val solidCard: Color,
    val chipSelected: Color,
    val chipUnselected: Color,
    val shadowTint: Color,
    val illustrationTint: Color,
    val warningTint: Color,
    val warmMist: Color,
    val coolMist: Color,
    val surfaceRaised: Color,
    val focusRing: Color,
    val receiptStub: ReceiptStubPalette,
)

val LocalThemeVisuals = compositionLocalOf { themeVisualsForSkin(AppSkin.Default) }

fun themeVisualsForSkin(skin: AppSkin): ThemeVisuals {
    return when (skin) {
        AppSkin.Paper -> ThemeVisuals(
            primary = Color(0xFF8A5A2B),
            primaryDark = Color(0xFF6F4621),
            accent = Color(0xFFD6B487),
            backgroundTop = Color(0xFFFBF8F1),
            backgroundBottom = Color(0xFFF3EFE6),
            heroGradient = listOf(
                Color(0xFF8A5A2B),
                Color(0xFFA86F38),
                Color(0xFF6F4621),
            ),
            heroGradientStart = Color(0xFF8A5A2B),
            heroGradientEnd = Color(0xFF6F4621),
            heroGlow = Color(0xFFD6B487),
            glassTint = Color(0xFFFBF8F1),
            solidCard = Color(0xFFFBF8F1),
            chipSelected = Color(0xFFEFE1CB),
            chipUnselected = Color(0xFFF5F0E3),
            shadowTint = Color(0xFF6F4621),
            illustrationTint = Color(0xFFD6B487),
            warningTint = Color(0xFFA4361C),
            warmMist = Color(0xFFEAD8B8),
            coolMist = Color(0xFFC8C2B3),
            surfaceRaised = Color(0xFFFFFFFF),
            focusRing = Color(0xFF8A5A2B),
            receiptStub = ReceiptStubPalette(
                paperTop = Color(0xFFFFFBF3),
                paperBottom = Color(0xFFF1E9DB),
                border = Color(0xFFE2D8C8),
                line = Color(0xFFBDB7AB),
                footer = Color(0xFFE0D5C4),
            ),
        )
        AppSkin.Mono -> ThemeVisuals(
            primary = Color(0xFF0E0E0C),
            primaryDark = Color(0xFF000000),
            accent = Color(0xFF6F6E6A),
            backgroundTop = Color(0xFFFAFAF8),
            backgroundBottom = Color(0xFFEDEDEA),
            heroGradient = listOf(
                Color(0xFF0E0E0C),
                Color(0xFF2C2B29),
                Color(0xFF000000),
            ),
            heroGradientStart = Color(0xFF0E0E0C),
            heroGradientEnd = Color(0xFF000000),
            heroGlow = Color(0xFFADACA7),
            glassTint = Color(0xFFFAFAF8),
            solidCard = Color(0xFFFAFAF8),
            chipSelected = Color(0xFFE3E2DD),
            chipUnselected = Color(0xFFF1F0ED),
            shadowTint = Color(0xFF0E0E0C),
            illustrationTint = Color(0xFFADACA7),
            warningTint = Color(0xFF8E1D12),
            warmMist = Color(0xFFE7DBC0),
            coolMist = Color(0xFFB8B7B3),
            surfaceRaised = Color(0xFFFFFFFF),
            focusRing = Color(0xFF0E0E0C),
            receiptStub = ReceiptStubPalette(
                paperTop = Color(0xFFFAFAF8),
                paperBottom = Color(0xFFEDEDEA),
                border = Color(0xFFD7D6D1),
                line = Color(0xFFACABA6),
                footer = Color(0xFFE0DFDA),
            ),
        )
        AppSkin.Midnight -> ThemeVisuals(
            primary = Color(0xFFD6B487),
            primaryDark = Color(0xFFB89564),
            accent = Color(0xFF8A6A3E),
            backgroundTop = Color(0xFF15171C),
            backgroundBottom = Color(0xFF0C0D10),
            heroGradient = listOf(
                Color(0xFF8A6A3E),
                Color(0xFFB89564),
                Color(0xFF15171C),
            ),
            heroGradientStart = Color(0xFF8A6A3E),
            heroGradientEnd = Color(0xFF15171C),
            heroGlow = Color(0xFFD6B487),
            glassTint = Color(0xFF1C1F25),
            solidCard = Color(0xFF15171C),
            chipSelected = Color(0xFF2A2D35),
            chipUnselected = Color(0xFF1C1F25),
            shadowTint = Color(0xFF000000),
            illustrationTint = Color(0xFF3A3E48),
            warningTint = Color(0xFFD97757),
            warmMist = Color(0xFF4D3617),
            coolMist = Color(0xFF8A6A3E),
            surfaceRaised = Color(0xFF222530),
            focusRing = Color(0xFFD6B487),
            receiptStub = ReceiptStubPalette(
                paperTop = Color(0xFF252830),
                paperBottom = Color(0xFF1A1D24),
                border = Color(0xFF3A3E48),
                line = Color(0xFF8A806F),
                footer = Color(0xFF343742),
            ),
        )
    }
}
