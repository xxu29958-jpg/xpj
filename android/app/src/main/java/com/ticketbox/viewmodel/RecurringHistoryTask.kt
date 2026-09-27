package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringQueryActions
import com.ticketbox.data.remote.dto.RecurringRevisionDto
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

data class RecurringHistoryState(
    val publicId: String? = null,
    val merchant: String = "",
    val items: List<RecurringRevisionDto> = emptyList(),
    val nextBeforeVersion: Long? = null,
    val loading: Boolean = false,
    val error: UiText? = null,
    val fetchedAt: String? = null,
    val fromCache: Boolean = false,
)

/** Each visible page keeps the source of its accepted query; an unread page cannot fill a gap. */
internal class RecurringHistoryTask(
    private val queries: RecurringQueryActions,
    private val scope: CoroutineScope,
    private val currentBinding: () -> LogicalSessionBinding?,
    private val publish: (RecurringHistoryState) -> Unit,
    private val onDenied: (Throwable) -> Unit,
) {
    private var state = RecurringHistoryState()
    private var job: Job? = null
    private var generation = 0L
    private var failedBefore: Long? = null

    fun dismiss() {
        generation += 1
        job?.cancel()
        state = RecurringHistoryState()
        publish(state)
    }

    fun open(item: RecurringItem) {
        val binding = currentBinding() ?: return
        if (item.ledgerId != binding.ledgerId) return
        dismiss()
        state = RecurringHistoryState(publicId = item.publicId, merchant = item.merchant)
        read(null)
    }

    fun more() { if (!state.loading && state.error == null) state.nextBeforeVersion?.let(::read) }
    fun retry() { if (!state.loading && state.error != null) read(failedBefore) }

    private fun read(before: Long?) {
        val binding = currentBinding() ?: return
        val id = state.publicId ?: return
        val sequence = ++generation
        failedBefore = before
        state = state.copy(loading = true, error = null)
        publish(state)
        job = scope.launch {
            val result = queries.history(binding, id, before)
            if (generation != sequence || currentBinding() != binding) return@launch
            result.fold(onSuccess = { read ->
                val page = read.value
                val rows = if (before == null) page.items else state.items + page.items
                state = state.copy(items = rows.distinctBy { it.rowVersion }, nextBeforeVersion = page.nextBeforeVersion,
                    loading = false,
                    fetchedAt = if (before == null) read.fetchedAt else listOfNotNull(state.fetchedAt, read.fetchedAt)
                        .minByOrNull { java.time.Instant.parse(it) },
                    fromCache = read.fromCache || (before != null && state.fromCache))
            }, onFailure = { error ->
                if (error.isReadAccessDenied()) {
                    state = RecurringHistoryState()
                    onDenied(error)
                } else state = state.copy(loading = false, error = error.toUiText(R.string.recurring_history_failed))
            })
            publish(state)
        }
    }
}
