package com.ticketbox.domain.model

/**
 * A ledger-scoped custom category option materialized after it is used.
 *
 * Default categories remain application vocabulary; this model represents only
 * server-owned additions that can be removed with optimistic concurrency.
 */
data class CategoryPreference(
    val publicId: String,
    val name: String,
    val kind: String,
    val usageCount: Int,
    val rowVersion: Long,
)

enum class CategoryReferenceKind { Rule, Budget, SpendingGoal }

data class CategoryReference(val kind: CategoryReferenceKind, val id: String, val label: String)

data class CategoryPreferenceInspection(val category: CategoryPreference, val references: List<CategoryReference>)
