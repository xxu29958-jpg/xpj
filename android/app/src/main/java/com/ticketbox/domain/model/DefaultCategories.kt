package com.ticketbox.domain.model

/**
 * 内置分类的命名字段：DEFAULT_EXPENSE_CATEGORIES 与展示映射（如流水分类图标）
 * 共同消费这些常量，展示侧不再重复书写中文 canonical 字面量。
 */
object DefaultExpenseCategories {
    const val DINING = "餐饮"
    const val TRANSIT = "交通"
    const val SHOPPING = "购物"
    const val ENTERTAINMENT = "娱乐"
    const val MEDICAL = "医疗"
    const val EDUCATION = "教育"
    const val HOUSING = "住房"
    const val TELECOM = "通讯"
    const val AI_SUBSCRIPTION = "AI订阅"
    const val DIGITAL = "数码"
    const val GAMES = "游戏"
    const val LIFE = "生活"
    const val OTHER = "其他"
}

val DEFAULT_EXPENSE_CATEGORIES = listOf(
    DefaultExpenseCategories.DINING,
    DefaultExpenseCategories.TRANSIT,
    DefaultExpenseCategories.SHOPPING,
    DefaultExpenseCategories.ENTERTAINMENT,
    DefaultExpenseCategories.MEDICAL,
    DefaultExpenseCategories.EDUCATION,
    DefaultExpenseCategories.HOUSING,
    DefaultExpenseCategories.TELECOM,
    DefaultExpenseCategories.AI_SUBSCRIPTION,
    DefaultExpenseCategories.DIGITAL,
    DefaultExpenseCategories.GAMES,
    DefaultExpenseCategories.LIFE,
    DefaultExpenseCategories.OTHER,
)

private val legacyCategoryAliases = mapOf(
    "吃饭" to DefaultExpenseCategories.DINING,
)

private val uncategorizedExpenseCategoryValues = setOf(
    "",
    "未分类",
    "未分類",
    "none",
    "null",
)

fun isUncategorizedExpenseCategory(value: String?): Boolean =
    value?.trim()?.lowercase().orEmpty() in uncategorizedExpenseCategoryValues

fun normalizeExpenseCategory(value: String?): String {
    val cleaned = value?.trim()?.takeIf { it.isNotBlank() } ?: DefaultExpenseCategories.OTHER
    return legacyCategoryAliases[cleaned] ?: cleaned
}

fun mergeExpenseCategories(values: List<String>): List<String> {
    val merged = linkedSetOf<String>()
    DEFAULT_EXPENSE_CATEGORIES.forEach { merged += it }
    values.map(::normalizeExpenseCategory).filter { it.isNotBlank() }.forEach { merged += it }
    return merged.toList()
}
