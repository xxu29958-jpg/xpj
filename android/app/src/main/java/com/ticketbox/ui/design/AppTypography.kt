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
 * 字重层级 token，按"焦点优先级"组织——下方注释说明使用边界。
 *
 * 现状审计发现 FontWeight.Black 在 UI 层有 69 处、Bold 29 处，
 * 所有文字都"高字重"导致信息层级失效（什么都重就什么都不重）。
 * 这套 token 用 4 级递进，约束新代码必须挑层级，而不是凭手感选字重。
 *
 * 旧代码迁移规则（在后续 commit 逐步替换 [AppTypography] 里的高字重 token）：
 *   - 列表项首行 / 卡片标题 / 商家名     → [body]    (Medium)
 *   - 分类标签 / 时间 / meta / 说明文字   → [caption] (Normal)
 *   - 大金额 / 页面主标题（每屏 1-2 个）  → [hero]    (Black)
 *   - 区块 section 标题                  → [heading] (SemiBold)
 */
object AppTextHierarchy {
    /** 页面唯一焦点：大金额、页面主标题。每屏 1-2 次。 */
    val hero = AppTextRole(size = 32.sp, weight = FontWeight.Black)

    /** 区块标题、卡片大标题。轻量强调，不抢主焦点。 */
    val heading = AppTextRole(size = 18.sp, weight = FontWeight.SemiBold)

    /** 列表项首行、商家名、内容正文。承担最多视觉量但不喧宾夺主。 */
    val body = AppTextRole(size = 15.sp, weight = FontWeight.Medium)

    /** 辅助信息：时间、分类标签、meta、说明文字。安静地存在。 */
    val caption = AppTextRole(size = 12.sp, weight = FontWeight.Normal)
}

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
