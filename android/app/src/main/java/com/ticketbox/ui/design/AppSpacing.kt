package com.ticketbox.ui.design

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

object AppSpacing {
    val none: Dp = 0.dp
    val tinyGap: Dp = 2.dp
    val miniGap: Dp = 4.dp
    val smallGap: Dp = 8.dp
    val contentGap: Dp = 10.dp
    val screenHorizontal: Dp = 24.dp
    val screenTop: Dp = 24.dp
    val sectionGap: Dp = 24.dp
    val cardGap: Dp = 16.dp
    val cardPaddingTight: Dp = 14.dp
    val cardPaddingSmall: Dp = 16.dp
    val cardPadding: Dp = 20.dp
    val compactGap: Dp = 12.dp
    val compactPadding: Dp = 10.dp
    val chipGap: Dp = 8.dp
    val bottomContentPadding: Dp = 24.dp
    /**
     * Minimum interactive target. Keep the visual glyph smaller when needed,
     * but never shrink the hit region below Android's 48dp accessibility floor.
     */
    val controlMinHeight: Dp = 48.dp
}
