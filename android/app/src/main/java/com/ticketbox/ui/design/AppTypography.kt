package com.ticketbox.ui.design

import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp

data class AppTextRole(
    val size: TextUnit,
    val lineHeight: TextUnit,
    val weight: FontWeight,
    val letterSpacing: TextUnit = 0.sp,
)

/**
 * 产品文字单源。字号、行高、字重和字距必须作为一个角色整体使用，
 * 页面和组件不得重新拼装局部数值。
 */
object AppTypeScale {
    val amountHero = AppTextRole(34.sp, 38.sp, FontWeight.ExtraBold, (-0.5).sp)
    val pageHero = AppTextRole(28.sp, 32.sp, FontWeight.Bold, (-0.25).sp)
    val pageTitle = AppTextRole(24.sp, 32.sp, FontWeight.Bold)
    val headline = AppTextRole(22.sp, 28.sp, FontWeight.Bold)
    val headlineQuiet = AppTextRole(22.sp, 28.sp, FontWeight.SemiBold)
    val sectionTitle = AppTextRole(18.sp, 24.sp, FontWeight.SemiBold)
    val cardTitle = AppTextRole(17.sp, 22.sp, FontWeight.SemiBold)
    val bodyStrong = AppTextRole(15.sp, 20.sp, FontWeight.Medium, 0.1.sp)
    val body = AppTextRole(14.sp, 22.sp, FontWeight.Normal, 0.15.sp)
    val caption = AppTextRole(12.sp, 17.sp, FontWeight.Normal, 0.25.sp)
    val captionCompact = AppTextRole(12.sp, 16.sp, FontWeight.Normal, 0.4.sp)
    val control = AppTextRole(15.sp, 20.sp, FontWeight.Medium, 0.1.sp)
    val controlCompact = AppTextRole(12.sp, 16.sp, FontWeight.Medium, 0.5.sp)
    val appLabel = AppTextRole(15.sp, 20.sp, FontWeight.SemiBold, 0.1.sp)
    val chip = AppTextRole(13.sp, 18.sp, FontWeight.Medium)
    val amountMedium = AppTextRole(22.sp, 26.sp, FontWeight.Bold)
}

object AppTypography {
    val appLabel = AppTypeScale.appLabel
    val pageTitle = AppTypeScale.pageTitle
    val sectionTitle = AppTypeScale.sectionTitle
    val cardTitle = AppTypeScale.cardTitle
    val amountLarge = AppTypeScale.amountHero
    val amountMedium = AppTypeScale.amountMedium
    val body = AppTypeScale.body
    val caption = AppTypeScale.controlCompact
    val chip = AppTypeScale.chip
}

/**
 * 四级内容层级。调用方选择语义角色，不选择字号。
 */
object AppTextHierarchy {
    /** 页面唯一焦点：大金额、页面主标题。每屏 1-2 次。 */
    val hero = AppTypeScale.pageHero

    /** 区块标题、卡片大标题。轻量强调，不抢主焦点。 */
    val heading = AppTypeScale.sectionTitle

    /** 列表项首行、商家名、内容正文。承担最多视觉量但不喧宾夺主。 */
    val body = AppTypeScale.bodyStrong

    /** 辅助信息：时间、分类标签、meta、说明文字。安静地存在。 */
    val caption = AppTypeScale.caption
}

fun AppTextRole.asTextStyle(): TextStyle = TextStyle(
    fontSize = size,
    lineHeight = lineHeight,
    fontWeight = weight,
    letterSpacing = letterSpacing,
)

/**
 * 为金额、tabular 数字列锁定等宽 digit 字形。
 *
 * 在 paper/journal 美学里，金额列必须按位对齐——没有 tabular-nums 时
 * Inter / system 字体的「8」和「1」宽度不同，造成柱式金额列错位。
 * 在 Text(style = ...) 上链式调用即可：
 *
 *   Text(
 *     text = formatDisplayAmount(cents, currencyDisplay),
 *     style = MaterialTheme.typography.headlineMedium.tabularNum(),
 *     fontWeight = AppTypography.amountLarge.weight,
 *   )
 */
fun TextStyle.tabularNum(): TextStyle = copy(fontFeatureSettings = "tnum")

/**
 * 金额排版"角色"——把两类强调金额的字号 / 字重 / 行高锁成命名档位。
 *
 * 金额收成三档单源：
 *   - [Hero]   —— 每屏唯一的焦点数字（月度总支出等），34sp ExtraBold。
 *   - [Medium] —— 卡片 / 列表里的次级金额，22sp Bold。
 *   - [Compact] —— 密集列表 / 明细行里的金额，15sp Medium。
 *
 * 字号、行高与字重来自同一 [AppTextRole]。配合 [asAmount] 使用。
 */
enum class AppAmountRole(val role: AppTextRole) {
    Hero(AppTypography.amountLarge),
    Medium(AppTypography.amountMedium),
    Compact(AppTextHierarchy.body),
}

/**
 * 金额排版制度单源：在任意基准 [TextStyle] 上套用一档 [AppAmountRole]——
 * 角色字号 / 字重 / 行高 + 字距归零 + 等宽数字（[tabularNum]）。
 *
 * 用 `copy` 而非新建 TextStyle：保留基准 style 的字族 / 色等其它属性，
 * 只覆盖金额需要锁定的几项，行为等价于此前手写的
 * `.copy(fontSize, lineHeight, letterSpacing = 0.sp, fontWeight).tabularNum()`。
 *
 *   Text(
 *     text = formatDisplayAmount(cents, currencyDisplay),
 *     style = MaterialTheme.typography.titleLarge.asAmount(AppAmountRole.Hero),
 *   )
 */
fun TextStyle.asAmount(amount: AppAmountRole): TextStyle = copy(
    fontSize = amount.role.size,
    lineHeight = amount.role.lineHeight,
    letterSpacing = 0.sp,
    fontWeight = amount.role.weight,
).tabularNum()
