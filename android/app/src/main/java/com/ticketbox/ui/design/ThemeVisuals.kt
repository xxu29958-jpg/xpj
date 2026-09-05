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
    val paperCard: Color,
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
    // 票面 coral 夹刻:纯品牌装饰(票/侧夹的形状色),不承载状态语义;
    // 镜像 shared/tokens.css 的 --brand-clip。只服务票面夹刻装饰,无消费者勿用。
    val clipCoral: Color,
)

val LocalThemeVisuals = compositionLocalOf { themeVisualsForSkin(AppSkin.Default) }

/** 当前已解析的渲染主题本身,供需要按 skin 切换图片资产等资源的消费点读取(如 mascot)。 */
val LocalAppSkin = compositionLocalOf { AppSkin.Default }

fun themeVisualsForSkin(skin: AppSkin): ThemeVisuals {
    return when (skin) {
        AppSkin.Paper -> ThemeVisuals(
            primary = Color(0xFF14504A),
            primaryDark = Color(0xFF0D3D38),
            accent = Color(0xFF7FAE9F),
            backgroundTop = Color(0xFFF5F9F6),
            backgroundBottom = Color(0xFFF5F9F6),
            heroGradient = listOf(
                Color(0xFF176B5B),
                Color(0xFF125C4F),
                Color(0xFF0E5146),
            ),
            heroGradientStart = Color(0xFF176B5B),
            heroGradientEnd = Color(0xFF0E5146),
            heroGlow = Color(0xFF86BBAA),
            paperCard = Color(0xFFFDFEFD),
            solidCard = Color(0xFFFDFEFD),
            chipSelected = Color(0xFFE1F0EA),
            chipUnselected = Color(0xFFEEF2EF),
            shadowTint = Color(0xFF17201C),
            illustrationTint = Color(0xFFA6C9BC),
            warningTint = Color(0xFFC0702C),
            warmMist = Color(0xFFE9EEE8),
            coolMist = Color(0xFFDCE4DF),
            surfaceRaised = Color(0xFFFDFEFD),
            focusRing = Color(0xFF14504A),
            receiptStub = ReceiptStubPalette(
                paperTop = Color(0xFFFFFFFF),
                paperBottom = Color(0xFFF4F6F3),
                border = Color(0xFFDCE2DD),
                line = Color(0xFFA8B2AC),
                footer = Color(0xFFEDF1EE),
            ),
            surfaceNav = Color(0xFFF8FBF9),
            surfaceSunken = Color(0xFFE9EFEB),
            textDefault = Color(0xFF1A201C),
            textMuted = Color(0xFF49504C),
            textMeta = Color(0xFF606762),
            textFaint = Color(0xFF8F9490),
            textOnPrimary = Color(0xFFFDFEFD),
            brandPrimaryBg = Color(0xFFE3EEEA),
            clipCoral = Color(0xFFC2492F),
        )
        AppSkin.Midnight -> ThemeVisuals(
            primary = Color(0xFF70BFA5),
            primaryDark = Color(0xFF54A187),
            accent = Color(0xFF33584C),
            backgroundTop = Color(0xFF111512),
            backgroundBottom = Color(0xFF111512),
            heroGradient = listOf(
                Color(0xFF315C50),
                Color(0xFF25483F),
                Color(0xFF151A17),
            ),
            heroGradientStart = Color(0xFF315C50),
            heroGradientEnd = Color(0xFF151A17),
            heroGlow = Color(0xFF69BFA4),
            paperCard = Color(0xFF1B1F1C),
            solidCard = Color(0xFF1B1F1C),
            chipSelected = Color(0xFF203B33),
            chipUnselected = Color(0xFF1C2320),
            shadowTint = Color(0xFF000000),
            illustrationTint = Color(0xFF31443D),
            warningTint = Color(0xFFE08261),
            warmMist = Color(0xFF26312C),
            coolMist = Color(0xFF29483F),
            surfaceRaised = Color(0xFF252B26),
            focusRing = Color(0xFF70BFA5),
            receiptStub = ReceiptStubPalette(
                paperTop = Color(0xFF202722),
                paperBottom = Color(0xFF171C19),
                border = Color(0xFF303A35),
                line = Color(0xFF66736D),
                footer = Color(0xFF252D28),
            ),
            surfaceNav = Color(0xFF161917),
            surfaceSunken = Color(0xFF212623),
            textDefault = Color(0xFFE9EDEA),
            textMuted = Color(0xFFAFB6B1),
            textMeta = Color(0xFF909893),
            textFaint = Color(0xFF5C625E),
            textOnPrimary = Color(0xFF0E1A17),
            brandPrimaryBg = Color(0x2E70BFA5),
            clipCoral = Color(0xFFEE6A4D),
        )
    }
}
