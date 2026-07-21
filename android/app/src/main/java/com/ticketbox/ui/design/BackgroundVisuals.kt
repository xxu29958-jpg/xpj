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
        AppSkin.Paper -> BackgroundVisuals(
            baseGradient = listOf(
                Color(0xFFF4F6F4),
                Color(0xFFF1F4F2),
                Color(0xFFEEF2EF),
            ),
            topGlow = Color(0xFFE1F0EA),
            topGlowAlpha = 0.12f,
            sideGlow = Color(0xFFDCE4DF),
            sideGlowAlpha = 0.08f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFFE7ECE8).copy(alpha = 0.16f),
                Color(0xFFDCE4DF).copy(alpha = 0.10f),
            ),
            textureTint = Color(0xFF66716B),
            textureAlpha = 0.04f,
        )
        AppSkin.Mono -> BackgroundVisuals(
            baseGradient = listOf(
                Color(0xFFF4F5F4),
                Color(0xFFF0F2F1),
                Color(0xFFECEFED),
            ),
            topGlow = Color(0xFFE5EAE7),
            topGlowAlpha = 0.10f,
            sideGlow = Color(0xFFD8DEDA),
            sideGlowAlpha = 0.08f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFFE5E9E6).copy(alpha = 0.14f),
                Color(0xFFD8DEDA).copy(alpha = 0.08f),
            ),
            textureTint = Color(0xFF626965),
            textureAlpha = 0.035f,
        )
        AppSkin.Midnight -> BackgroundVisuals(
            baseGradient = listOf(
                Color(0xFF151A17),
                Color(0xFF121714),
                Color(0xFF0F1311),
            ),
            topGlow = Color(0xFF69BFA4),
            topGlowAlpha = 0.10f,
            sideGlow = Color(0xFF315C50),
            sideGlowAlpha = 0.12f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFF202722).copy(alpha = 0.24f),
                Color(0xFF111513).copy(alpha = 0.18f),
            ),
            textureTint = Color(0xFF69BFA4),
            textureAlpha = 0.035f,
        )
    }
}
