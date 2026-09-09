package com.ticketbox.ui.screens.settings.categoryrules

import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents

data class CategoryRuleDraftForm(
    val keyword: String = "",
    val category: String = "",
    val priorityText: String = "10",
    val editingRule: CategoryRule? = null,
    val localMessage: UiText? = null,
    val minimumAmount: String = "",
    val maximumAmount: String = "",
    val homeCurrencyCode: String? = null,
) {
    val currency: CurrencyCode? get() = CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)
    val hasUnconfirmedOriginalAmount: Boolean get() = editingRule?.let {
        (it.amountMinCents != null || it.amountMaxCents != null) && CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode) == null
    } == true

    fun toRequest(): Result<CategoryRuleRequest> = runCatching {
        requireInput(keyword.isNotBlank() && category.isNotBlank(), R.string.category_rule_validation_fields)
        val priority = priorityText.toIntOrNull() ?: throw CategoryRuleInputError(R.string.category_rule_validation_priority)
        requireInput(!hasUnconfirmedOriginalAmount, R.string.category_rule_currency_review)
        val min = parseBound(minimumAmount)
        val max = parseBound(maximumAmount)
        requireInput(min == null || max == null || min <= max, R.string.category_rule_validation_range)
        CategoryRuleRequest(keyword.trim(), category.trim(), editingRule?.enabled ?: true, priority,
            min, max, editingRule?.sourceContains, editingRule?.tagContains,
            homeCurrencyCode = homeCurrencyCode.takeIf { min != null || max != null || editingRule?.homeCurrencyCode != null })
    }

    private fun parseBound(raw: String): Long? {
        if (raw.isBlank()) return null
        val selected = currency ?: throw CategoryRuleInputError(R.string.category_rule_validation_currency)
        return parseAmountCents(raw, selected)?.takeIf { it >= 0 } ?: throw CategoryRuleInputError(R.string.category_rule_validation_amount)
    }

    companion object {
        fun fromRule(rule: CategoryRule): CategoryRuleDraftForm {
            val currency = CurrencyCode.fromStorageKeyOrNull(rule.homeCurrencyCode)
            fun amount(raw: Long?): String = if (currency == null) raw?.toString().orEmpty() else formatAmountInput(raw, currency)
            return CategoryRuleDraftForm(rule.keyword, rule.category, rule.priority.toString(), rule,
                minimumAmount = amount(rule.amountMinCents), maximumAmount = amount(rule.amountMaxCents),
                homeCurrencyCode = rule.homeCurrencyCode)
        }
    }
}

internal class CategoryRuleInputError(val resourceId: Int) : IllegalArgumentException()

private fun requireInput(valid: Boolean, resourceId: Int) {
    if (!valid) throw CategoryRuleInputError(resourceId)
}
