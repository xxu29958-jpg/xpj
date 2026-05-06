package com.ticketbox.ui.design

import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp

data class AppTextRole(
    val size: TextUnit,
    val weight: FontWeight,
)

object AppTypography {
    val appLabel = AppTextRole(size = 15.sp, weight = FontWeight.Black)
    val pageTitle = AppTextRole(size = 28.sp, weight = FontWeight.Black)
    val sectionTitle = AppTextRole(size = 20.sp, weight = FontWeight.Black)
    val cardTitle = AppTextRole(size = 17.sp, weight = FontWeight.Bold)
    val amountLarge = AppTextRole(size = 38.sp, weight = FontWeight.Black)
    val amountMedium = AppTextRole(size = 24.sp, weight = FontWeight.Black)
    val body = AppTextRole(size = 14.sp, weight = FontWeight.Normal)
    val caption = AppTextRole(size = 12.sp, weight = FontWeight.Medium)
    val chip = AppTextRole(size = 13.sp, weight = FontWeight.Bold)
}
