package com.ticketbox.ui.design

import com.ticketbox.domain.model.AppSkin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ThemeVisualsTest {
    @Test
    fun everySkinHasCompleteThemeVisuals() {
        AppSkin.entries.forEach { skin ->
            val visuals = themeVisualsForSkin(skin)

            assertTrue(visuals.heroGradient.size >= 2, "$skin hero gradient should have at least two colors")
            assertTrue(visuals.primary.alpha > 0.99f, "$skin primary should be opaque")
            assertTrue(visuals.solidCard.alpha > 0.99f, "$skin solid card should be opaque")
            assertTrue(visuals.paperCard.alpha > 0.99f, "$skin paper card should be opaque")
            assertTrue(visuals.shadowTint.alpha > 0.99f, "$skin shadow tint should be opaque")
            assertTrue(visuals.backgroundTop.alpha > 0.99f, "$skin background top should be opaque")
            assertTrue(visuals.backgroundBottom.alpha > 0.99f, "$skin background bottom should be opaque")
        }
    }

    @Test
    fun defaultSkinIsPaper() {
        assertEquals(AppSkin.Paper, AppSkin.Default)
    }

    @Test
    fun exactlyTwoSkinsAreShipped() {
        // 2 套主题 (Paper / Midnight)；mono 已退役，无历史数据不保留映射。
        // 修改本断言前先确认 shared/tokens.css 与 ThemeVisuals 同步更新。
        assertEquals(2, AppSkin.entries.size)
    }

    @Test
    fun everySkinHasSurfaceRaisedAndFocusRing() {
        AppSkin.entries.forEach { skin ->
            val visuals = themeVisualsForSkin(skin)
            assertTrue(visuals.surfaceRaised.alpha > 0.99f, "$skin surfaceRaised should be opaque")
            assertTrue(visuals.focusRing.alpha > 0.99f, "$skin focusRing should be opaque")
        }
    }

    @Test
    fun everySkinHasCompleteStateTokens() {
        AppSkin.entries.forEach { skin ->
            val state = stateTokensForSkin(skin)
            listOf(state.success, state.warn, state.danger, state.info, state.neutral).forEach { tone ->
                assertTrue(tone.bg != tone.fg, "$skin state tone bg and fg must differ")
                assertTrue(tone.bg.alpha > 0.99f, "$skin state bg should be opaque")
                assertTrue(tone.fg.alpha > 0.99f, "$skin state fg should be opaque")
            }
        }
    }

    @Test
    fun everySkinHasEightChartSeriesColors() {
        AppSkin.entries.forEach { skin ->
            val chart = chartTokensForSkin(skin)
            assertEquals(8, chart.series.size, "$skin chart series should have exactly 8 colors")
            assertEquals(chart.series.size, chart.series.distinct().size, "$skin chart series colors should be distinct")
            assertTrue(chart.tooltipBg != chart.tooltipFg, "$skin tooltip bg and fg must differ")
            assertTrue(chart.divergingNegative != chart.divergingPositive, "$skin diverging negative and positive must differ")
        }
    }

    @Test
    fun everySkinHasFiveGoalStateTokens() {
        AppSkin.entries.forEach { skin ->
            val goal = goalTokensForSkin(skin)
            val states = listOf(goal.idle, goal.onTrack, goal.nearLimit, goal.exceeded, goal.expired)
            states.forEach { tone ->
                assertTrue(tone.bg != tone.fg, "$skin goal state bg and fg must differ")
            }
            assertTrue(goal.onTrack.fg != goal.exceeded.fg, "$skin onTrack and exceeded should be visually distinct")
        }
    }

}
