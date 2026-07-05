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
            resolveAppAdaptiveMetricGridMode(AppAdaptiveBreakpoints.singleColumnMaxWidth),
        )
    }

    @Test
    fun metricGridUsesTwoColumnsAbovePhoneWidth() {
        assertEquals(
            AppAdaptiveMetricGridMode.TwoColumn,
            resolveAppAdaptiveMetricGridMode(AppAdaptiveBreakpoints.singleColumnMaxWidth + 1.dp),
        )
    }
}
