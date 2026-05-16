package com.ticketbox.ui.design

import androidx.compose.ui.text.TextStyle
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

/**
 * 为金额、tabular 数字列锁定等宽 digit 字形。
 *
 * 在 paper/journal 美学里，金额列必须按位对齐——没有 tabular-nums 时
 * Inter / system 字体的「8」和「1」宽度不同，造成柱式金额列错位。
 * 在 Text(style = ...) 上链式调用即可：
 *
 *   Text(
 *     text = formatAmount(cents),
 *     style = MaterialTheme.typography.headlineMedium.tabularNum(),
 *     fontWeight = AppTypography.amountLarge.weight,
 *   )
 */
fun TextStyle.tabularNum(): TextStyle = copy(fontFeatureSettings = "tnum")
