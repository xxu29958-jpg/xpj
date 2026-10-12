package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.BillSplitAcceptPayload
import com.ticketbox.data.repository.LogicalSessionBinding

@JsonClass(generateAdapter = true)
internal data class BillSplitAcceptanceDraft(val binding: LogicalSessionBinding, val original: BillSplitAcceptPayload)

/** Unsubmitted selection only. The existing Room Outbox owns every admitted acceptance. */
internal class BillSplitAcceptanceDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().build().adapter<List<BillSplitAcceptanceDraft>>(
        Types.newParameterizedType(List::class.java, BillSplitAcceptanceDraft::class.java))
    private val key = "bill.split.acceptance.selections"
    private fun all(): List<BillSplitAcceptanceDraft> = state.get<String>(key)?.let { adapter.fromJson(it) }.orEmpty()

    fun read(binding: LogicalSessionBinding): Map<String, BillSplitAcceptPayload> =
        all().filter { it.binding == binding }.associate { it.original.publicId to it.original }

    fun select(binding: LogicalSessionBinding, original: BillSplitAcceptPayload) {
        state[key] = adapter.toJson(all().filterNot { it.binding == binding && it.original.publicId == original.publicId } +
            BillSplitAcceptanceDraft(binding, original))
    }

    fun remove(binding: LogicalSessionBinding, publicId: String) {
        state[key] = adapter.toJson(all().filterNot { it.binding == binding && it.original.publicId == publicId })
    }
}
