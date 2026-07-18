package com.ticketbox.ui.components

import kotlin.test.Test
import kotlin.test.assertEquals

class AppAdaptivePaneStructuresTest {
    @Test
    fun allFiveProductDomainsDeclareDistinctPrimaryAndSupportingPurposes() {
        val structures = AppAdaptivePaneStructures.All

        assertEquals(AppAdaptiveProductDomain.entries.toSet(), structures.map { it.domain }.toSet())
        assertEquals(
            listOf(
                AppAdaptivePanePurpose.ReviewQueue to AppAdaptivePanePurpose.IntakeAndTriage,
                AppAdaptivePanePurpose.TransactionRegister to AppAdaptivePanePurpose.RegisterControls,
                AppAdaptivePanePurpose.ObligationList to AppAdaptivePanePurpose.ObligationNavigation,
                AppAdaptivePanePurpose.PlanOverview to AppAdaptivePanePurpose.FixedArrangements,
                AppAdaptivePanePurpose.InsightResults to AppAdaptivePanePurpose.InsightControls,
            ),
            structures.map { it.primaryPurpose to it.supportingPurpose },
        )
        assertEquals(
            structures.size * 2,
            structures.flatMap { listOf(it.primaryTestTag, it.supportingTestTag) }.distinct().size,
        )
    }
}
