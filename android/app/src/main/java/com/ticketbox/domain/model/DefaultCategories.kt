package com.ticketbox.domain.model

val DEFAULT_EXPENSE_CATEGORIES = listOf(
    "餐饮",
    "交通",
    "购物",
    "娱乐",
    "医疗",
    "教育",
    "住房",
    "通讯",
    "AI订阅",
    "数码",
    "游戏",
    "生活",
    "其他",
)

private val legacyCategoryAliases = mapOf(
    "吃饭" to "餐饮",
)

fun normalizeExpenseCategory(value: String?): String {
    val cleaned = value?.trim()?.takeIf { it.isNotBlank() } ?: "其他"
    return legacyCategoryAliases[cleaned] ?: cleaned
}

fun mergeExpenseCategories(values: List<String>): List<String> {
    val merged = linkedSetOf<String>()
    DEFAULT_EXPENSE_CATEGORIES.forEach { merged += it }
    values.map(::normalizeExpenseCategory).filter { it.isNotBlank() }.forEach { merged += it }
    return merged.toList()
}
