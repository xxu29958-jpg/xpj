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
}
