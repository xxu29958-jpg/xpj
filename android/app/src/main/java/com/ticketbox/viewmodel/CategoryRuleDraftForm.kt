package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.CategoryRuleDefinition
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.presentation.formatAmountInput
import com.ticketbox.presentation.parseAmountCents
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RuleDefinitionDraft

data class CategoryRuleDraftForm(
    val keyword: String = "",
    val category: String = "",
    val priorityText: String = "10",
    val editingRule: CategoryRule? = null,
    val localMessage: UiText? = null,
    val minimumAmount: String = "",
    val maximumAmount: String = "",
    val homeCurrencyCode: String? = null,
    val sourceContains: String = "",
    val tagContains: String = "",
) {
    val currency: CurrencyCode? get() = CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)
    val hasUnconfirmedOriginalAmount: Boolean get() = editingRule?.let {
        (it.amountMinCents != null || it.amountMaxCents != null) && CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode) == null
    } == true

    fun toRequest(): Result<CategoryRuleDefinition> = runCatching {
        requireInput(keyword.isNotBlank() && category.isNotBlank(), R.string.category_rule_validation_fields)
        val priority = priorityText.toIntOrNull() ?: throw CategoryRuleInputError(R.string.category_rule_validation_priority)
        requireInput(!hasUnconfirmedOriginalAmount, R.string.category_rule_currency_review)
        val min = parseBound(minimumAmount)
        val max = parseBound(maximumAmount)
        requireInput(min == null || max == null || min <= max, R.string.category_rule_validation_range)
        CategoryRuleDefinition(keyword.trim(), category.trim(), editingRule?.enabled ?: true, priority,
            min, max, sourceContains.trim().takeIf { it.isNotEmpty() }, tagContains.trim().takeIf { it.isNotEmpty() },
            homeCurrencyCode = homeCurrencyCode.takeIf { min != null || max != null || editingRule?.homeCurrencyCode != null })
    }

    private fun parseBound(raw: String): Long? {
        if (raw.isBlank()) return null
        val selected = currency ?: throw CategoryRuleInputError(R.string.category_rule_validation_currency)
        return parseAmountCents(raw, selected)?.takeIf { it >= 0 } ?: throw CategoryRuleInputError(R.string.category_rule_validation_amount)
    }

    fun toDraft(binding: LogicalSessionBinding, key: String) = RuleDefinitionDraft(binding, key,
        keyword, category, priorityText, editingRule, minimumAmount, maximumAmount, homeCurrencyCode, sourceContains, tagContains)

    companion object {
        fun fromDraft(draft: RuleDefinitionDraft) = CategoryRuleDraftForm(draft.keyword, draft.category,
            draft.priorityText, draft.baseline, minimumAmount = draft.minimumAmount, maximumAmount = draft.maximumAmount,
            homeCurrencyCode = draft.homeCurrencyCode, sourceContains = draft.sourceContains, tagContains = draft.tagContains)

        fun fromRule(rule: CategoryRule): CategoryRuleDraftForm {
            val currency = CurrencyCode.fromStorageKeyOrNull(rule.homeCurrencyCode)
            fun amount(raw: Long?): String = if (currency == null) raw?.toString().orEmpty() else formatAmountInput(raw, currency)
            return CategoryRuleDraftForm(rule.keyword, rule.category, rule.priority.toString(), rule,
                minimumAmount = amount(rule.amountMinCents), maximumAmount = amount(rule.amountMaxCents),
                homeCurrencyCode = rule.homeCurrencyCode, sourceContains = rule.sourceContains.orEmpty(), tagContains = rule.tagContains.orEmpty())
        }
    }
}

internal class CategoryRuleInputError(val resourceId: Int) : IllegalArgumentException()

private fun requireInput(valid: Boolean, resourceId: Int) {
    if (!valid) throw CategoryRuleInputError(resourceId)
}
