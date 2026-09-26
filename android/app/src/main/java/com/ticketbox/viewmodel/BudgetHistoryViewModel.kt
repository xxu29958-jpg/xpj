package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.BudgetHistoryReader
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.BudgetRevision
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

data class BudgetHistoryState(
    val month: String = "",
    val items: List<BudgetRevision> = emptyList(),
    val nextBeforeVersion: Long? = null,
    val loading: Boolean = false,
    val failed: Boolean = false,
)

class BudgetHistoryViewModel(private val repository: BudgetHistoryReader) : ViewModel() {
    private val mutableState = MutableStateFlow(BudgetHistoryState())
    val state = mutableState.asStateFlow()
    private var binding: LogicalSessionBinding? = null
    private var sequence = 0L
    private var failedCursor: Long? = null

    init {
        viewModelScope.launch {
            repository.observeActiveLedgerAccess().map { it?.binding }.distinctUntilChanged().collect {
                binding = it
                ++sequence
                mutableState.value = BudgetHistoryState(month = mutableState.value.month)
                if (mutableState.value.month.isNotEmpty()) load(null)
            }
        }
    }

    fun open(month: String) {
        ++sequence
        mutableState.value = BudgetHistoryState(month = month)
        load(null)
    }

    fun next() {
        mutableState.value.nextBeforeVersion?.let(::load)
    }

    fun retry() = load(failedCursor)

    private fun load(cursor: Long?) {
        if (mutableState.value.loading) return
        val expectedBinding = binding
        if (expectedBinding == null) {
            failedCursor = cursor
            mutableState.value = mutableState.value.copy(failed = true)
            return
        }
        val request = ++sequence
        val month = mutableState.value.month
        mutableState.value = mutableState.value.copy(loading = true, failed = false)
        viewModelScope.launch {
            val result = repository.history(expectedBinding, month, cursor)
            if (request != sequence || binding != expectedBinding) return@launch
            result.onSuccess { page ->
                mutableState.value = BudgetHistoryState(month = month,
                    items = if (cursor == null) page.items else mutableState.value.items + page.items,
                    nextBeforeVersion = page.nextBeforeVersion)
            }.onFailure { error ->
                failedCursor = cursor
                val refused = (error as? RepositoryException)?.httpStatusCode?.let { it in 400..499 } == true
                if (refused) failedCursor = null
                mutableState.value = mutableState.value.copy(
                    items = if (refused) emptyList() else mutableState.value.items, loading = false, failed = true)
            }
        }
    }
}

fun budgetHistoryViewModelFactory(repository: BudgetHistoryReader): ViewModelProvider.Factory =
    object : ViewModelProvider.Factory {
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            requireNotNull(modelClass.cast(BudgetHistoryViewModel(repository)))
    }
