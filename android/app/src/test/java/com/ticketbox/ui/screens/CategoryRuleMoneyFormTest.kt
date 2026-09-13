package com.ticketbox.ui.screens

import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleDraftForm
import com.ticketbox.domain.model.CategoryRule
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class CategoryRuleMoneyFormTest {
    @Test fun unselectedMoneyCurrencyCannotBecomeRenminbi() {
        val form = CategoryRuleDraftForm(keyword = "旅行", category = "交通", minimumAmount = "1200")
        assertTrue(form.toRequest().isFailure)
        val request = form.copy(homeCurrencyCode = "JPY").toRequest().getOrThrow()
        assertEquals(1200L, request.amountMinCents)
        assertEquals("JPY", request.homeCurrencyCode)
    }

    @Test fun keywordOnlyRuleDoesNotNeedMoneyConfigurationAndInvalidBoundsStayDrafts() {
        val form = CategoryRuleDraftForm(keyword = "交通", category = "交通")
        assertEquals(null, form.toRequest().getOrThrow().homeCurrencyCode)
        assertTrue(form.copy(homeCurrencyCode = "JPY", minimumAmount = "1200", maximumAmount = "100").toRequest().isFailure)
        assertTrue(form.copy(homeCurrencyCode = "JPY", minimumAmount = "1.20").toRequest().isFailure)
    }

    @Test fun editAndClearKeepCapturedCurrencyWhileLegacyMoneyCannotBeRewritten() {
        val rule = CategoryRule(id = 7, keyword = "旅行", category = "交通", enabled = true, priority = 10,
            amountMinCents = 1200, amountMaxCents = 5000, sourceContains = null, tagContains = null,
            createdAt = "2026-09-09", updatedAt = "2026-09-09", rowVersion = 2, homeCurrencyCode = "JPY")
        val form = CategoryRuleDraftForm.fromRule(rule)
        assertEquals("1200", form.minimumAmount)
        val cleared = form.copy(minimumAmount = "", maximumAmount = "").toRequest().getOrThrow()
        assertEquals("JPY", cleared.homeCurrencyCode)
        assertEquals(null, cleared.amountMinCents)
        assertEquals(null, cleared.amountMaxCents)
        val legacy = CategoryRuleDraftForm.fromRule(rule.copy(homeCurrencyCode = null))
        assertEquals("1200", legacy.minimumAmount)
        assertTrue(legacy.copy(homeCurrencyCode = "CNY").toRequest().isFailure)
    }
}
