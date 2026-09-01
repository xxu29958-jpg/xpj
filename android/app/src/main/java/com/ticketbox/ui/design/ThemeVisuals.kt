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
    // v0.10.1 镜像 shared/tokens.css 余下 surface / text / brand 语义,
    // 让三端语义对照表完整。原本由 MaterialTheme.colorScheme 兜底的字段
    // (onBackground/onSurfaceVariant 等) 现在通过显式字段表达,Android Screen
    // 不再依赖 Material You 默认。
    val surfaceNav: Color,
    val surfaceSunken: Color,
    val textDefault: Color,
    val textMuted: Color,
    val textMeta: Color,
    val textFaint: Color,
    val textOnPrimary: Color,
    val brandPrimaryBg: Color,
)

val LocalThemeVisuals = compositionLocalOf { themeVisualsForSkin(AppSkin.Default) }

fun themeVisualsForSkin(skin: AppSkin): ThemeVisuals {
    return when (skin) {
        AppSkin.Paper -> ThemeVisuals(
            primary = Color(0xFF176B5B),
            primaryDark = Color(0xFF0E5146),
            accent = Color(0xFF86BBAA),
            backgroundTop = Color(0xFFF4F6F4),
            backgroundBottom = Color(0xFFEEF2EF),
            heroGradient = listOf(
                Color(0xFF176B5B),
                Color(0xFF125C4F),
                Color(0xFF0E5146),
            ),
            heroGradientStart = Color(0xFF176B5B),
            heroGradientEnd = Color(0xFF0E5146),
            heroGlow = Color(0xFF86BBAA),
            glassTint = Color(0xFFFFFFFF),
            solidCard = Color(0xFFFFFFFF),
            chipSelected = Color(0xFFE1F0EA),
            chipUnselected = Color(0xFFEEF2EF),
            shadowTint = Color(0xFF17201C),
            illustrationTint = Color(0xFFA6C9BC),
            warningTint = Color(0xFFC0702C),
            warmMist = Color(0xFFE9EEE8),
            coolMist = Color(0xFFDCE4DF),
            surfaceRaised = Color(0xFFFFFFFF),
            focusRing = Color(0xFF176B5B),
            receiptStub = ReceiptStubPalette(
                paperTop = Color(0xFFFFFFFF),
                paperBottom = Color(0xFFF4F6F3),
                border = Color(0xFFDCE2DD),
                line = Color(0xFFA8B2AC),
                footer = Color(0xFFEDF1EE),
            ),
            surfaceNav = Color(0xFFFFFFFF),
            surfaceSunken = Color(0xFFEEF2EF),
            textDefault = Color(0xFF17201C),
            textMuted = Color(0xFF66716B),
            textMeta = Color(0xFF87928C),
            textFaint = Color(0xFFB7C0BB),
            textOnPrimary = Color(0xFFFFFFFF),
            brandPrimaryBg = Color(0xFFE1F0EA),
        )
        AppSkin.Midnight -> ThemeVisuals(
            primary = Color(0xFF69BFA4),
            primaryDark = Color(0xFF4A9D84),
            accent = Color(0xFF315C50),
            backgroundTop = Color(0xFF151A17),
            backgroundBottom = Color(0xFF0F1311),
            heroGradient = listOf(
                Color(0xFF315C50),
                Color(0xFF25483F),
                Color(0xFF151A17),
            ),
            heroGradientStart = Color(0xFF315C50),
            heroGradientEnd = Color(0xFF151A17),
            heroGlow = Color(0xFF69BFA4),
            glassTint = Color(0xFF1A201D),
            solidCard = Color(0xFF171C19),
            chipSelected = Color(0xFF203B33),
            chipUnselected = Color(0xFF1C2320),
            shadowTint = Color(0xFF000000),
            illustrationTint = Color(0xFF31443D),
            warningTint = Color(0xFFE08261),
            warmMist = Color(0xFF26312C),
            coolMist = Color(0xFF29483F),
            surfaceRaised = Color(0xFF202722),
            focusRing = Color(0xFF69BFA4),
            receiptStub = ReceiptStubPalette(
                paperTop = Color(0xFF202722),
                paperBottom = Color(0xFF171C19),
                border = Color(0xFF303A35),
                line = Color(0xFF66736D),
                footer = Color(0xFF252D28),
            ),
            surfaceNav = Color(0xFF111513),
            surfaceSunken = Color(0xFF1C2320),
            textDefault = Color(0xFFE8EEEA),
            textMuted = Color(0xFFAAB5AF),
            textMeta = Color(0xFF77837D),
            textFaint = Color(0xFF46514B),
            textOnPrimary = Color(0xFF0D1D18),
            brandPrimaryBg = Color(0x2E69BFA4),
        )
    }
}
