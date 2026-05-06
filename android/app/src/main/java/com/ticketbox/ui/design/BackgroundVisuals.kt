package com.ticketbox.ui.design

import androidx.compose.ui.graphics.Color
import com.ticketbox.domain.model.AppSkin

data class BackgroundVisuals(
    val baseGradient: List<Color>,
    val topGlow: Color,
    val topGlowAlpha: Float,
    val sideGlow: Color,
    val sideGlowAlpha: Float,
    val bottomMist: List<Color>,
    val textureTint: Color,
    val textureAlpha: Float,
)

fun backgroundVisualsForSkin(skin: AppSkin): BackgroundVisuals {
    return when (skin) {
        AppSkin.Pine -> BackgroundVisuals(
            baseGradient = listOf(
                Color(0xFFFAF8EF),
                Color(0xFFF1F5EF),
                Color(0xFFDCEBE5),
            ),
            topGlow = Color(0xFFF4E5C9),
            topGlowAlpha = 0.34f,
            sideGlow = Color(0xFF8FB9A8),
            sideGlowAlpha = 0.28f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFFAFCDBE).copy(alpha = 0.24f),
                Color(0xFF6E9A86).copy(alpha = 0.16f),
            ),
            textureTint = Color(0xFF7EA18F),
            textureAlpha = 0.10f,
        )
        AppSkin.Harbor -> BackgroundVisuals(
            baseGradient = listOf(
                Color(0xFFFBF8F0),
                Color(0xFFEFF7F8),
                Color(0xFFD5E8F0),
            ),
            topGlow = Color(0xFFF1DDBE),
            topGlowAlpha = 0.28f,
            sideGlow = Color(0xFF73ABC4),
            sideGlowAlpha = 0.34f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFFB3D3DF).copy(alpha = 0.25f),
                Color(0xFF7FAEC4).copy(alpha = 0.18f),
            ),
            textureTint = Color(0xFF6A9EB4),
            textureAlpha = 0.10f,
        )
        AppSkin.Pomelo -> BackgroundVisuals(
            baseGradient = listOf(
                Color(0xFFFFFAED),
                Color(0xFFF9ECD5),
                Color(0xFFEFE0C2),
            ),
            topGlow = Color(0xFFFFD17A),
            topGlowAlpha = 0.30f,
            sideGlow = Color(0xFFE2B765),
            sideGlowAlpha = 0.22f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFFE8D0A3).copy(alpha = 0.22f),
            ),
            textureTint = Color(0xFFD8A64D),
            textureAlpha = 0.08f,
        )
        AppSkin.Berry -> BackgroundVisuals(
            baseGradient = listOf(
                Color(0xFFFFF6F8),
                Color(0xFFF8EBF0),
                Color(0xFFEEE3E8),
            ),
            topGlow = Color(0xFFE9A1B6),
            topGlowAlpha = 0.28f,
            sideGlow = Color(0xFFC96C86),
            sideGlowAlpha = 0.18f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFFE5D5DC).copy(alpha = 0.22f),
            ),
            textureTint = Color(0xFFC68296),
            textureAlpha = 0.08f,
        )
        AppSkin.Night -> BackgroundVisuals(
            baseGradient = listOf(
                Color(0xFF041018),
                Color(0xFF071B20),
                Color(0xFF0A2529),
            ),
            topGlow = Color(0xFF2BB49A),
            topGlowAlpha = 0.22f,
            sideGlow = Color(0xFF245D78),
            sideGlowAlpha = 0.26f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFF123A3E).copy(alpha = 0.22f),
            ),
            textureTint = Color(0xFF2BB49A),
            textureAlpha = 0.08f,
        )
    }
}
