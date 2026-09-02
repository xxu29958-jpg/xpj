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
            primary = Color(0xFF14504A),
            primaryDark = Color(0xFF0D3D38),
            accent = Color(0xFF7FAE9F),
            backgroundTop = Color(0xFFF4F6F4),
            backgroundBottom = Color(0xFFF6F2EA),
            heroGradient = listOf(
                Color(0xFF176B5B),
                Color(0xFF125C4F),
                Color(0xFF0E5146),
            ),
            heroGradientStart = Color(0xFF176B5B),
            heroGradientEnd = Color(0xFF0E5146),
            heroGlow = Color(0xFF86BBAA),
            glassTint = Color(0xFFFFFFFF),
            solidCard = Color(0xFFFFFDF8),
            chipSelected = Color(0xFFE1F0EA),
            chipUnselected = Color(0xFFEEF2EF),
            shadowTint = Color(0xFF17201C),
            illustrationTint = Color(0xFFA6C9BC),
            warningTint = Color(0xFFC0702C),
            warmMist = Color(0xFFE9EEE8),
            coolMist = Color(0xFFDCE4DF),
            surfaceRaised = Color(0xFFFFFDF8),
            focusRing = Color(0xFF14504A),
            receiptStub = ReceiptStubPalette(
                paperTop = Color(0xFFFFFFFF),
                paperBottom = Color(0xFFF4F6F3),
                border = Color(0xFFDCE2DD),
                line = Color(0xFFA8B2AC),
                footer = Color(0xFFEDF1EE),
            ),
            surfaceNav = Color(0xFFFAF6EE),
            surfaceSunken = Color(0xFFEFE9DC),
            textDefault = Color(0xFF1D1A15),
            textMuted = Color(0xFF57514A),
            textMeta = Color(0xFF6F6860),
            textFaint = Color(0xFFABA294),
            textOnPrimary = Color(0xFFFFFFFF),
            brandPrimaryBg = Color(0xFFE2ECDF),
        )
        AppSkin.Midnight -> ThemeVisuals(
            primary = Color(0xFF70BFA5),
            primaryDark = Color(0xFF54A187),
            accent = Color(0xFF33584C),
            backgroundTop = Color(0xFF151A17),
            backgroundBottom = Color(0xFF14120D),
            heroGradient = listOf(
                Color(0xFF315C50),
                Color(0xFF25483F),
                Color(0xFF151A17),
            ),
            heroGradientStart = Color(0xFF315C50),
            heroGradientEnd = Color(0xFF151A17),
            heroGlow = Color(0xFF69BFA4),
            glassTint = Color(0xFF1A201D),
            solidCard = Color(0xFF1D1A13),
            chipSelected = Color(0xFF203B33),
            chipUnselected = Color(0xFF1C2320),
            shadowTint = Color(0xFF000000),
            illustrationTint = Color(0xFF31443D),
            warningTint = Color(0xFFE08261),
            warmMist = Color(0xFF26312C),
            coolMist = Color(0xFF29483F),
            surfaceRaised = Color(0xFF272319),
            focusRing = Color(0xFF70BFA5),
            receiptStub = ReceiptStubPalette(
                paperTop = Color(0xFF202722),
                paperBottom = Color(0xFF171C19),
                border = Color(0xFF303A35),
                line = Color(0xFF66736D),
                footer = Color(0xFF252D28),
            ),
            surfaceNav = Color(0xFF12100B),
            surfaceSunken = Color(0xFF221E15),
            textDefault = Color(0xFFECE7DB),
            textMuted = Color(0xFFB3AB9C),
            textMeta = Color(0xFF8A8172),
            textFaint = Color(0xFF57503F),
            textOnPrimary = Color(0xFF0E1A17),
            brandPrimaryBg = Color(0x2E70BFA5),
        )
    }
}
