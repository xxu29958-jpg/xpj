package com.ticketbox.ui.design

import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp

data class AppTextRole(
    val size: TextUnit,
    val weight: FontWeight,
)

/**
 * 旧 token 集 —— 保持兼容。
 *
 * v0.10 字重重平衡（2026-05）：
 * - `appLabel` Black → SemiBold（应用标记不该和 amountLarge 同等级）
 * - `sectionTitle` Black → SemiBold（section 头不是页面唯一焦点）
 * - `cardTitle` Bold → SemiBold（卡内标题比 section 还轻一级）
 * - `amountMedium` Black → Bold（次级金额不与主 hero 同等级）
 * - `chip` Bold → Medium（chip 是辅助元素，Bold 在 12px 字号上视觉过重）
 * - 保留 Black：`pageTitle` / `amountLarge` —— 这两个才是每屏唯一焦点
 *
 * 新代码请优先使用 [AppTextHierarchy] 的 4 级层级。
 */
object AppTypography {
    val appLabel = AppTextRole(size = 15.sp, weight = FontWeight.SemiBold)
    val pageTitle = AppTextRole(size = 28.sp, weight = FontWeight.Black)
    val sectionTitle = AppTextRole(size = 20.sp, weight = FontWeight.SemiBold)
    val cardTitle = AppTextRole(size = 17.sp, weight = FontWeight.SemiBold)
    val amountLarge = AppTextRole(size = 38.sp, weight = FontWeight.Black)
    val amountMedium = AppTextRole(size = 24.sp, weight = FontWeight.Bold)
    val body = AppTextRole(size = 14.sp, weight = FontWeight.Normal)
    val caption = AppTextRole(size = 12.sp, weight = FontWeight.Medium)
    val chip = AppTextRole(size = 13.sp, weight = FontWeight.Medium)
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

/**
 * 金额排版"角色"——把两类强调金额的字号 / 字重 / 行高锁成命名档位。
 *
 * 此前各屏都手写 `MaterialTheme.typography.titleLarge.copy(fontSize = …,
 * lineHeight = …, letterSpacing = 0.sp, fontWeight = …).tabularNum()`，字号 /
 * 行高靠手感复制、容易漂。这里把"焦点金额"收成两档单源：
 *   - [Hero]   —— 每屏唯一的英雄数字（月度总支出等），38sp Black。
 *   - [Medium] —— 卡片 / 列表里的次级金额，24sp Bold。
 *
 * 字号 / 字重直接复用 [AppTypography] 的 `amountLarge` / `amountMedium`，
 * 不再写第二份字面量；只补金额特有的行高。配合 [asAmount] 使用。
 */
enum class AppAmountRole(val role: AppTextRole, val lineHeight: TextUnit) {
    Hero(AppTypography.amountLarge, 38.sp),
    Medium(AppTypography.amountMedium, 28.sp),
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
    lineHeight = amount.lineHeight,
    letterSpacing = 0.sp,
    fontWeight = amount.role.weight,
).tabularNum()
