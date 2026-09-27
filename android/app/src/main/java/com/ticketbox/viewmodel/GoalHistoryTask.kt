package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.GoalRevision
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

data class GoalHistoryState(
    val visible: Boolean = false,
    val items: List<GoalRevision> = emptyList(),
    val nextBeforeVersion: Long? = null,
    val loading: Boolean = false,
    val error: UiText? = null,
    val fromCache: Boolean = false,
    val fetchedAt: String? = null,
)

/** Detail-owned reading task; it never writes a goal or its original submission. */
internal class GoalHistoryTask(
    private val reports: ReportsActions,
    private val scope: CoroutineScope,
    private val currentTask: () -> Pair<LogicalSessionBinding, String>?,
    private val publish: (GoalHistoryState) -> Unit,
) {
    private var state = GoalHistoryState()
    private var job: Job? = null
    private var generation = 0L
    private var failedBefore: Long? = null

    fun reset() {
        generation += 1
        job?.cancel()
        state = GoalHistoryState()
        publish(state)
    }

    fun dismiss() {
        generation += 1
        job?.cancel()
        state = state.copy(visible = false, loading = false)
        publish(state)
    }

    fun open() {
        if (state.visible) return
        state = GoalHistoryState(visible = true)
        read(null)
    }

    fun refresh() {
        if (!state.visible) return
        generation += 1
        job?.cancel()
        state = GoalHistoryState(visible = true)
        read(null)
    }

    fun more() { if (!state.loading && state.error == null) state.nextBeforeVersion?.let(::read) }
    fun retry() { if (!state.loading && state.error != null) read(failedBefore) }

    private fun read(before: Long?) {
        val task = currentTask() ?: return
        val sequence = ++generation
        failedBefore = before
        state = state.copy(loading = true, error = null)
        publish(state)
        job = scope.launch {
            val result = reports.goalHistory(task.second, before, task.first)
            if (sequence != generation || currentTask() != task) return@launch
            result.fold(onSuccess = { read ->
                val rows = if (before == null) read.value.items else state.items + read.value.items
                state = state.copy(items = rows.distinctBy { it.rowVersion }, nextBeforeVersion = read.value.nextBeforeVersion,
                    loading = false, fromCache = state.fromCache || read.fromCache, fetchedAt = read.fetchedAt)
            }, onFailure = { error ->
                state = if (error.isReadAccessDenied()) GoalHistoryState() else state.copy(loading = false,
                    error = error.toUiText(R.string.goal_history_failed))
            })
            publish(state)
        }
    }
}
