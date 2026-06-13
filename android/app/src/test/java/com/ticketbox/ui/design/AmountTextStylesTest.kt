package com.ticketbox.ui.design

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * 金额排版制度单源 [asAmount] / [AppAmountRole] 的回归钉。各屏焦点金额迁到这套
 * API 后，字号 / 字重 / 行高 / 等宽数字若被悄悄改动会在这里炸出来——这类回退
 * （金额列又不对齐、英雄数字缩水）肉眼很难一眼察觉。
 */
class AmountTextStylesTest {
    @Test
    fun heroRoleAppliesTabularFiguresAndHeroDimensions() {
        val style = TextStyle().asAmount(AppAmountRole.Hero)
        assertEquals("tnum", style.fontFeatureSettings)
        assertEquals(38.sp, style.fontSize)
        assertEquals(38.sp, style.lineHeight)
        assertEquals(0.sp, style.letterSpacing)
        assertEquals(FontWeight.Black, style.fontWeight)
    }

    @Test
    fun mediumRoleAppliesTabularFiguresAndMediumDimensions() {
        val style = TextStyle().asAmount(AppAmountRole.Medium)
        assertEquals("tnum", style.fontFeatureSettings)
        assertEquals(24.sp, style.fontSize)
        assertEquals(28.sp, style.lineHeight)
        assertEquals(0.sp, style.letterSpacing)
        assertEquals(FontWeight.Bold, style.fontWeight)
    }

    @Test
    fun asAmountPreservesUnrelatedBaseStyleProperties() {
        // copy 语义：只覆盖金额要锁的几项，基准 style 的色等其它属性保留，这样
        // call site 写 MaterialTheme.typography.titleLarge.asAmount(...) 仍带主题字色 / 字族。
        val style = TextStyle(color = Color.Red).asAmount(AppAmountRole.Hero)
        assertEquals(Color.Red, style.color)
    }

    @Test
    fun rolesReuseAppTypographyAnchorsWithoutDuplicatingLiterals() {
        // 角色的字号 / 字重直接取 AppTypography 的 amountLarge / amountMedium，不另写
        // 第二份字面量——钉住"同源"，防两处字号各自漂移。
        assertEquals(AppTypography.amountLarge, AppAmountRole.Hero.role)
        assertEquals(AppTypography.amountMedium, AppAmountRole.Medium.role)
    }
}
