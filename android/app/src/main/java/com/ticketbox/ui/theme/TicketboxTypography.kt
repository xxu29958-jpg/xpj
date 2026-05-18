package com.ticketbox.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppTypography

/**
 * Material3 Typography 派生自 [AppTextHierarchy] / [AppTypography]。
 *
 * v0.10.1 (2026-05) 加入,与 shared/tokens.css 的 `--type-*` scale 对齐：
 *   M3 token              ↔  shared --type-*  ↔  AppTextHierarchy / AppTypography
 *   displayLarge          ↔  display (38/900)  ↔  AppTypography.amountLarge
 *   displayMedium         ↔  hero    (28/900)  ↔  AppTypography.pageTitle
 *   displaySmall          ↔  hero    (28/900)
 *   headlineLarge         ↔  headline(22/700)
 *   headlineMedium        ↔  headline(22/700)  ↔  AppTextHierarchy.hero(降级)
 *   headlineSmall         ↔  title   (18/600)  ↔  AppTextHierarchy.heading
 *   titleLarge            ↔  title   (18/600)  ↔  AppTextHierarchy.heading
 *   titleMedium           ↔  subtitle(15/500)  ↔  AppTextHierarchy.body
 *   titleSmall            ↔  subtitle(15/500)
 *   bodyLarge             ↔  body    (14/400)
 *   bodyMedium            ↔  caption (12/400)  ↔  AppTextHierarchy.caption
 *   bodySmall             ↔  caption (12/400)
 *   labelLarge            ↔  subtitle(15/500)  —— Button 等控件
 *   labelMedium           ↔  caption (12/500)
 *   labelSmall            ↔  meta    (10/500)
 *
 * v0.10.1 (2026-05) 已通过 `Theme.kt` 的 `MaterialTheme(typography = TicketboxTypography)`
 * 全局注入。后续如需调整阶梯,直接改本文件 + shared/tokens.css 的 `--type-*`,
 * 不要在 Screen 里写硬编码 `TextStyle(fontSize = X.sp)`。
 */
val TicketboxTypography: Typography = Typography(
    displayLarge = TextStyle(
        fontSize = AppTypography.amountLarge.size,
        lineHeight = 40.sp,
        fontWeight = AppTypography.amountLarge.weight,
        letterSpacing = (-0.5).sp,
    ),
    displayMedium = TextStyle(
        fontSize = AppTypography.pageTitle.size,
        lineHeight = 32.sp,
        fontWeight = AppTypography.pageTitle.weight,
        letterSpacing = (-0.25).sp,
    ),
    displaySmall = TextStyle(
        fontSize = AppTypography.pageTitle.size,
        lineHeight = 32.sp,
        fontWeight = AppTypography.pageTitle.weight,
    ),
    headlineLarge = TextStyle(
        fontSize = 22.sp,
        lineHeight = 28.sp,
        fontWeight = FontWeight.Bold,
    ),
    headlineMedium = TextStyle(
        fontSize = 22.sp,
        lineHeight = 28.sp,
        fontWeight = FontWeight.SemiBold,
    ),
    headlineSmall = TextStyle(
        fontSize = AppTextHierarchy.heading.size,
        lineHeight = 24.sp,
        fontWeight = AppTextHierarchy.heading.weight,
    ),
    titleLarge = TextStyle(
        fontSize = AppTextHierarchy.heading.size,
        lineHeight = 24.sp,
        fontWeight = AppTextHierarchy.heading.weight,
    ),
    titleMedium = TextStyle(
        fontSize = AppTextHierarchy.body.size,
        lineHeight = 21.sp,
        fontWeight = AppTextHierarchy.body.weight,
        letterSpacing = 0.10.sp,
    ),
    titleSmall = TextStyle(
        fontSize = AppTextHierarchy.body.size,
        lineHeight = 21.sp,
        fontWeight = AppTextHierarchy.body.weight,
    ),
    bodyLarge = TextStyle(
        fontSize = AppTypography.body.size,
        lineHeight = 22.sp,
        fontWeight = AppTypography.body.weight,
        letterSpacing = 0.15.sp,
    ),
    bodyMedium = TextStyle(
        fontSize = AppTextHierarchy.caption.size,
        lineHeight = 17.sp,
        fontWeight = AppTextHierarchy.caption.weight,
        letterSpacing = 0.25.sp,
    ),
    bodySmall = TextStyle(
        fontSize = AppTextHierarchy.caption.size,
        lineHeight = 16.sp,
        fontWeight = AppTextHierarchy.caption.weight,
        letterSpacing = 0.4.sp,
    ),
    labelLarge = TextStyle(
        fontSize = AppTextHierarchy.body.size,
        lineHeight = 20.sp,
        fontWeight = FontWeight.Medium,
        letterSpacing = 0.10.sp,
    ),
    labelMedium = TextStyle(
        fontSize = AppTextHierarchy.caption.size,
        lineHeight = 16.sp,
        fontWeight = FontWeight.Medium,
        letterSpacing = 0.5.sp,
    ),
    labelSmall = TextStyle(
        fontSize = 10.sp,
        lineHeight = 14.sp,
        fontWeight = FontWeight.Medium,
        letterSpacing = 0.5.sp,
    ),
)
