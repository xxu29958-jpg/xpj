package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReceivablesActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0049 P3b / ⑤c (slice ⑤c-2) 欠我的(应收) —— 跨账本 member 应收的**只读发现面**。
 *
 * 家人接受你发起的拆账后，你作为跨账本债权人的那些应收（ledger-scoped 的 [DebtListViewModel] 看不到，
 * 因为 bill_split 成员债住在债务人的账本）汇总在这里。所有行都是 member 应收（服务端保证
 * `viewer_is_debtor=false`），纯只读（无 create / 无写）。
 *
 * 镜像 [DebtListViewModel] 的 [loadGeneration] 单调代际守卫：被新 refresh 超越的慢加载直接丢弃。应收是
 * **账户作用域**（跨账本）、与活跃账本无关，故不像 DebtListViewModel 那样按账本清旧数据（无 reload）——
 * 只在每次（重新）进入 overlay 时 [refresh] 拉最新。
 */
data class ReceivablesUiState(
    val isLoading: Boolean = false,
    val receivables: List<Debt> = emptyList(),
    val error: UiText? = null,
)

class ReceivablesViewModel(
    private val repository: ReceivablesActions,
) : ViewModel() {

    private val _state = MutableStateFlow(ReceivablesUiState())
    val state: StateFlow<ReceivablesUiState> = _state.asStateFlow()

    // Monotonic load token (mirrors DebtListViewModel): a refresh applies its result only if it is
    // still the latest. The init load + the refresh on every overlay (re-)entry each bump it, so a
    // slow earlier fetch can't overwrite newer data — it just drops.
    private var loadGeneration = 0L

    init {
        refresh()
    }

    fun refresh() {
        val gen = ++loadGeneration
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.listReceivables()
            // Drop a load superseded by a newer refresh (which set isLoading and owns clearing it).
            if (gen != loadGeneration) return@launch
            result.fold(
                onSuccess = { debts ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            receivables = sortReceivablesActiveFirst(debts),
                            error = null,
                        )
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(isLoading = false, error = err.toUiText(R.string.receivables_load_failed))
                    }
                },
            )
        }
    }
}

/**
 * Active-first ordering: open receivables first, cleared/voided recede to the bottom. The server
 * returns ``status.asc`` (alphabetical → cleared before open), so the client re-sorts — mirroring
 * the debt list's ``groupDebtsForList`` on both Android and web. Kotlin [sortedBy] is stable, so the
 * server's created order is preserved within a status rank.
 */
internal fun sortReceivablesActiveFirst(debts: List<Debt>): List<Debt> =
    debts.sortedBy { receivableStatusRank(it.status) }

private fun receivableStatusRank(status: String): Int = when (status) {
    DebtLinkStatuses.OPEN -> 0
    DebtLinkStatuses.CLEARED -> 1
    else -> 2 // voided / 未知
}
