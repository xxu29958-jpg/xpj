package com.ticketbox.data.repository

import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleDraftForm
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RuleDefinitionInputRoomTest {
    private val fixture = ExpenseCorrectionConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)

    @After fun close() = fixture.close()

    @Test fun reopeningKeepsInvalidRawMoneyOriginalRuleVersionAndIndependentNewInput() = runBlocking {
        val repository = fixture.reopen().ruleRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        val baseline = CategoryRule(19, "原关键词", "交通", false, 7, 1200, null, "原来源", "原标签",
            "2026-10-08", "2026-10-08", 4, "JPY")
        val original = RuleDefinitionDraft(binding, "original-edit", "  原始关键词  ", "家庭交通", "not-yet-a-number",
            baseline, "1.20", "", "JPY", "  新来源  ", "  新标签  ")
        val creation = original.copy(key = "independent-new", baseline = null, keyword = "  另一份新规则  ")
        requireNotNull(repository.definitionInputs).write(original)
        requireNotNull(repository.definitionInputs).write(creation)
        val reopened = fixture.reopen().ruleRepository
        val retained = requireNotNull(reopened.definitionInputs).read(binding)
        assertEquals(setOf(original, creation), retained.toSet())
        assertTrue(CategoryRuleDraftForm.fromDraft(retained.first { it.key == original.key }).toRequest().isFailure)
        assertTrue(requireNotNull(reopened.definitionInputs).read(binding.copy(ownerKey = "another-owner")).isEmpty())
        assertTrue(requireNotNull(reopened.definitionInputs).read(binding.copy(ledgerId = "another-ledger")).isEmpty())
        assertTrue(requireNotNull(reopened.definitionInputs).read(binding.copy(serverUrl = "https://another.invalid")).isEmpty())
        fixture.switchAccount()
        assertTrue(reopened.updateCategoryRule(binding, baseline,
            CategoryRuleRequest("原始关键词", "交通", false, 7, 1200, homeCurrencyCode = "JPY"), original).isFailure)
        assertEquals(emptyList<Map<String, String?>>(), fixture.stored())
        assertEquals(setOf(original, creation), requireNotNull(reopened.definitionInputs).read(binding).toSet())
    }

    @Test fun onlyTheExactInputIsAtomicallyHandedToOneOutboxSubmission() = runBlocking {
        val repository = fixture.reopen().ruleRepository
        val binding = requireNotNull(repository.currentAccess()).binding
        val original = RuleDefinitionDraft(binding, "original-rule-create", "  月票  ", "交通", "10",
            minimumAmount = "1200", homeCurrencyCode = "JPY", sourceContains = "  扫描  ", tagContains = "  家庭  ")
        val store = requireNotNull(repository.definitionInputs)
        store.write(original)
        val later = original.copy(keyword = "  后来输入的月票  ")
        store.write(later)
        assertTrue(repository.createCategoryRule(binding, CategoryRuleDraftForm.fromDraft(original).toRequest().getOrThrow(), original).isFailure)
        assertTrue(fixture.stored().isEmpty())
        assertEquals(listOf(later), store.read(binding))
        val request = CategoryRuleDraftForm.fromDraft(later).toRequest().getOrThrow()
        repository.createCategoryRule(binding, request, later).getOrThrow()
        val row = fixture.stored().single()
        assertEquals(original.key, row["idempotencyKey"])
        assertEquals("0", row["expectedRowVersion"])
        assertEquals("pending", row["status"])
        val pending = requireNotNull(repository.describeSubmission(fixture.outbox.activeForTarget("category_rule_create:${original.key}").single()))
        assertEquals(later.originalFields(), pending.originalInput)
        assertTrue(requireNotNull(row["payload"]).contains("后来输入的月票"))
        assertTrue(store.read(binding).isEmpty())
        assertTrue(repository.createCategoryRule(binding, request, later).isFailure)
        assertEquals(listOf(row), fixture.stored())
        val reopened = fixture.reopen().ruleRepository
        assertTrue(requireNotNull(reopened.definitionInputs).read(binding).isEmpty())
        assertEquals(listOf(row), fixture.stored())
    }
}
