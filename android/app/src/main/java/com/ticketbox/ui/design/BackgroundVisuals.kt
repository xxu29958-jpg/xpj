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
                Color(0xFFFBF8F1),
                Color(0xFFF5F0E3),
                Color(0xFFF3EFE6),
            ),
            topGlow = Color(0xFFEAD8B8),
            topGlowAlpha = 0.32f,
            sideGlow = Color(0xFFD6B487),
            sideGlowAlpha = 0.22f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFFE2D6C0).copy(alpha = 0.24f),
                Color(0xFFC8B895).copy(alpha = 0.16f),
            ),
            textureTint = Color(0xFF807968),
            textureAlpha = 0.10f,
        )
        AppSkin.Mono -> BackgroundVisuals(
            baseGradient = listOf(
                Color(0xFFFAFAF8),
                Color(0xFFF1F0ED),
                Color(0xFFEDEDEA),
            ),
            topGlow = Color(0xFFE0DFDA),
            topGlowAlpha = 0.32f,
            sideGlow = Color(0xFFC6C5C0),
            sideGlowAlpha = 0.20f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFFDADAD5).copy(alpha = 0.24f),
                Color(0xFFB8B7B3).copy(alpha = 0.14f),
            ),
            textureTint = Color(0xFF6F6E6A),
            textureAlpha = 0.08f,
        )
        AppSkin.Midnight -> BackgroundVisuals(
            baseGradient = listOf(
                Color(0xFF15171C),
                Color(0xFF1C1F25),
                Color(0xFF0C0D10),
            ),
            topGlow = Color(0xFFD6B487),
            topGlowAlpha = 0.18f,
            sideGlow = Color(0xFF8A6A3E),
            sideGlowAlpha = 0.22f,
            bottomMist = listOf(
                Color.Transparent,
                Color(0xFF2A2D35).copy(alpha = 0.36f),
                Color(0xFF15171C).copy(alpha = 0.24f),
            ),
            textureTint = Color(0xFFD6B487),
            textureAlpha = 0.06f,
        )
    }
}
