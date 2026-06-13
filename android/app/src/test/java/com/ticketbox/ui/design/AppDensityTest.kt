package com.ticketbox.ui.design

import androidx.compose.ui.unit.dp
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * 列表行密度档位 [AppDensity] 的回归钉。Comfortable / Compact 两档的数值锚定在
 * ExpenseCard 迁移前的取值上（迁到 token 后渲染应逐字节不变）；三档之间必须严格
 * 越来越密，避免出现"换了档位却没变化"的死档。
 */
class AppDensityTest {
    @Test
    fun comfortableAndCompactMatchExpenseCardLegacyValues() {
        val comfortable = AppDensity.rowMetrics(AppListDensity.Comfortable)
        assertEquals(14.dp, comfortable.rowPadding)
        assertEquals(12.dp, comfortable.contentGap)
        assertEquals(12.dp, comfortable.itemSpacing)
        assertEquals(6.dp, comfortable.labelGap)

        val compact = AppDensity.rowMetrics(AppListDensity.Compact)
        assertEquals(10.dp, compact.rowPadding)
        assertEquals(8.dp, compact.contentGap)
        assertEquals(10.dp, compact.itemSpacing)
        assertEquals(4.dp, compact.labelGap)
    }

    @Test
    fun standardTierSitsBetweenComfortableAndCompact() {
        val standard = AppDensity.rowMetrics(AppListDensity.Standard)
        assertEquals(12.dp, standard.rowPadding)
        assertEquals(10.dp, standard.contentGap)
        assertEquals(11.dp, standard.itemSpacing)
        assertEquals(5.dp, standard.labelGap)
    }

    @Test
    fun tiersGetStrictlyDenserFromComfortableToCompact() {
        val comfortable = AppDensity.rowMetrics(AppListDensity.Comfortable)
        val standard = AppDensity.rowMetrics(AppListDensity.Standard)
        val compact = AppDensity.rowMetrics(AppListDensity.Compact)
        // 每一项都 Comfortable > Standard > Compact（越紧凑留白越小，无重复 / 无死档）。
        listOf(
            Triple(comfortable.rowPadding, standard.rowPadding, compact.rowPadding),
            Triple(comfortable.contentGap, standard.contentGap, compact.contentGap),
            Triple(comfortable.itemSpacing, standard.itemSpacing, compact.itemSpacing),
            Triple(comfortable.labelGap, standard.labelGap, compact.labelGap),
        ).forEach { (comfy, std, tight) ->
            assertTrue(comfy > std, "comfortable $comfy should exceed standard $std")
            assertTrue(std > tight, "standard $std should exceed compact $tight")
        }
    }
}
