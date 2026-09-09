package com.ticketbox.ui.screens.settings.categoryrules

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
    val localMessage: String? = null,
    val minimumAmount: String = "",
    val maximumAmount: String = "",
    val homeCurrencyCode: String? = null,
) {
    val currency: CurrencyCode? get() = CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)
    val hasUnconfirmedOriginalAmount: Boolean get() = editingRule?.let {
        (it.amountMinCents != null || it.amountMaxCents != null) && CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode) == null
    } == true

    fun toRequest(): Result<CategoryRuleRequest> = runCatching {
        require(keyword.isNotBlank() && category.isNotBlank()) { "请填写关键词和分类。" }
        val priority = requireNotNull(priorityText.toIntOrNull()) { "优先级需要填写整数。" }
        require(!hasUnconfirmedOriginalAmount) { "原规则金额币种尚未确认，原数值已保留，请先核对。" }
        val min = parseBound(minimumAmount)
        val max = parseBound(maximumAmount)
        require(min == null || max == null || min <= max) { "金额下限不能大于上限。" }
        CategoryRuleRequest(keyword.trim(), category.trim(), editingRule?.enabled ?: true, priority,
            min, max, editingRule?.sourceContains, editingRule?.tagContains,
            homeCurrencyCode = homeCurrencyCode.takeIf { min != null || max != null || editingRule?.homeCurrencyCode != null })
    }

    private fun parseBound(raw: String): Long? {
        if (raw.isBlank()) return null
        val selected = requireNotNull(currency) { "请先选择金额条件使用的币种。" }
        return requireNotNull(parseAmountCents(raw, selected)?.takeIf { it >= 0 }) { "请按所选币种填写有效金额。" }
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
