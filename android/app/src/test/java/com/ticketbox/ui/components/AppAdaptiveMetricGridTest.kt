package com.ticketbox.ui.components

import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import kotlin.test.Test
import kotlin.test.assertEquals

class AppAdaptiveMetricGridTest {
    @Test
    fun metricGridUsesSingleColumnAtPhoneWidth() {
        assertEquals(
            AppAdaptiveMetricGridMode.SingleColumn,
            resolveAppAdaptiveMetricGridMode(AppAdaptiveBreakpoints.mediumWidthMin - 1.dp),
        )
    }

    @Test
    fun metricGridUsesTwoColumnsAbovePhoneWidth() {
        assertEquals(
            AppAdaptiveMetricGridMode.TwoColumn,
            resolveAppAdaptiveMetricGridMode(AppAdaptiveBreakpoints.mediumWidthMin),
        )
    }

    @Test
    fun compactGridUsesTwoColumnsAtPhoneWidth() {
        assertEquals(
            AppAdaptiveMetricGridMode.TwoColumn,
            resolveAppAdaptiveMetricGridMode(
                maxWidth = AppAdaptiveMetricGridCompactMinWidth,
                twoColumnMinWidth = AppAdaptiveMetricGridCompactMinWidth,
            ),
        )
    }

    @Test
    fun compactGridStaysSingleColumnBelowCompactWidth() {
        assertEquals(
            AppAdaptiveMetricGridMode.SingleColumn,
            resolveAppAdaptiveMetricGridMode(
                maxWidth = AppAdaptiveMetricGridCompactMinWidth - 1.dp,
                twoColumnMinWidth = AppAdaptiveMetricGridCompactMinWidth,
            ),
        )
    }

    @Test
    fun compactGridUsesTwoColumnsAtRealPhoneContentWidth() {
        // 实测锁定（真机 review-fix 图）：360dp 屏真实内容宽 312dp，不是 360dp。
        assertEquals(
            AppAdaptiveMetricGridMode.TwoColumn,
            resolveAppAdaptiveMetricGridMode(
                maxWidth = 312.dp,
                twoColumnMinWidth = AppAdaptiveMetricGridCompactMinWidth,
            ),
        )
    }
}
