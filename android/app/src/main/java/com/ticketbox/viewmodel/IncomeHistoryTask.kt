package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.IncomeHistoryPage
import com.ticketbox.domain.model.IncomeRevision
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

data class IncomeHistoryState(
    val publicId: String? = null,
    val items: List<IncomeRevision> = emptyList(),
    val nextBeforeVersion: Long? = null,
    val loading: Boolean = false,
    val error: UiText? = null,
)

/** Reads saved revisions without touching the income editor, draft or submission. */
internal class IncomeHistoryTask(
    private val readPage: suspend (LogicalSessionBinding, String, Long?) -> Result<IncomeHistoryPage>,
    private val scope: CoroutineScope,
    private val currentBinding: () -> LogicalSessionBinding?,
    private val publish: (IncomeHistoryState) -> Unit,
) {
    private var state = IncomeHistoryState()
    private var sequence = 0L
    private var job: Job? = null
    private var failedBefore: Long? = null

    fun dismiss() {
        sequence += 1
        job?.cancel()
        state = IncomeHistoryState()
        publish(state)
    }

    fun open(publicId: String) {
        dismiss()
        state = IncomeHistoryState(publicId = publicId)
        read(null)
    }

    fun refresh() { state.publicId?.let(::open) }
    fun more() { if (!state.loading && state.error == null) state.nextBeforeVersion?.let(::read) }
    fun retry() { if (!state.loading && state.error != null) read(failedBefore) }

    private fun read(before: Long?) {
        val binding = currentBinding() ?: return
        val publicId = state.publicId ?: return
        val request = ++sequence
        failedBefore = before
        state = state.copy(loading = true, error = null)
        publish(state)
        job = scope.launch {
            val result = readPage(binding, publicId, before)
            if (request != sequence || currentBinding() != binding) return@launch
            state = result.fold(onSuccess = { page ->
                state.copy(items = if (before == null) page.items else state.items + page.items,
                    nextBeforeVersion = page.nextBeforeVersion, loading = false)
            }, onFailure = { error ->
                if (error.isReadAccessDenied()) IncomeHistoryState() else state.copy(loading = false,
                    error = error.toUiText(R.string.income_history_failed))
            })
            publish(state)
        }
    }
}
