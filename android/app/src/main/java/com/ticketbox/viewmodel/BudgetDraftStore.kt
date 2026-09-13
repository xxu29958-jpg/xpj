package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.LogicalSessionBinding

@JsonClass(generateAdapter = true)
internal data class BudgetDraftSnapshot(
    val binding: LogicalSessionBinding,
    val month: String,
    val form: BudgetFormState,
)

/** Android saved state owns raw, unsubmitted input; Room owns accepted queue entries. */
internal class BudgetDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().build().adapter<List<BudgetDraftSnapshot>>(
        Types.newParameterizedType(List::class.java, BudgetDraftSnapshot::class.java),
    )
    private val drafts: List<BudgetDraftSnapshot>
        get() = state.get<String>("budget.drafts")?.let { adapter.fromJson(it) }.orEmpty()

    fun read(binding: LogicalSessionBinding, month: String): BudgetFormState? =
        drafts.firstOrNull { it.binding == binding && it.month == month }?.form

    fun write(binding: LogicalSessionBinding, month: String, form: BudgetFormState) {
        state["budget.drafts"] = adapter.toJson(drafts.filterNot { it.binding == binding && it.month == month } +
            BudgetDraftSnapshot(binding, month, form))
    }

    fun remove(binding: LogicalSessionBinding, month: String, expected: BudgetFormState? = null) {
        state["budget.drafts"] = adapter.toJson(drafts.filterNot {
            it.binding == binding && it.month == month && (expected == null || expected == it.form)
        })
    }
}
