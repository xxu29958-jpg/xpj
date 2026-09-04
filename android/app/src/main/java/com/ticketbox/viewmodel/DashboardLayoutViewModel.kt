package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DashboardCardsActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class DashboardLayoutUiState(
    val cards: List<DashboardCard>? = null,
    val draft: List<DashboardCard>? = null,
    val loading: Boolean = false,
    val saving: Boolean = false,
    val canModify: Boolean = false,
    val loadError: UiText? = null,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
)

class DashboardLayoutViewModel(private val repository: DashboardCardsActions) : ViewModel() {
    private val _uiState = MutableStateFlow(DashboardLayoutUiState())
    val uiState = _uiState.asStateFlow()
    private var binding: LogicalSessionBinding? = null
    private var generation = 0

    fun refresh() {
        val access = repository.dashboardAccess()
        if (access?.binding != binding) {
            binding = access?.binding
            generation += 1
            _uiState.value = DashboardLayoutUiState(canModify = access?.canModify == true)
        }
        _uiState.update { it.copy(canModify = access?.canModify == true) }
        val requestBinding = binding ?: return
        // Rotation/foreground refresh must not replace an open draft or its save receipt.
        if (_uiState.value.draft != null || _uiState.value.saving) return
        val request = ++generation
        _uiState.update { it.copy(loading = true, loadError = null) }
        viewModelScope.launch {
            val result = repository.dashboardCards(requestBinding)
            if (!isCurrent(request, requestBinding)) return@launch
            result.fold(
                onSuccess = { cards ->
                    _uiState.update { it.copy(cards = cards.items.sortedBy { card -> card.position }, loading = false) }
                },
                onFailure = { error ->
                    _uiState.update { it.copy(loading = false, loadError = error.toUiText(R.string.dashboard_load_failed)) }
                },
            )
        }
    }

    fun beginEdit() {
        val state = _uiState.value
        if (!state.canModify || state.saving) return
        val cards = state.cards ?: return
        generation += 1
        _uiState.update { it.copy(draft = cards, loading = false, message = null) }
    }

    fun setVisible(key: String, visible: Boolean) = changeDraft { cards ->
        cards.map { if (it.key == key) it.copy(visible = visible) else it }
    }

    fun move(key: String, delta: Int) = changeDraft { cards ->
        val index = cards.indexOfFirst { it.key == key }
        val target = index + delta
        if (index < 0 || target !in cards.indices) cards else cards.toMutableList().apply { add(target, removeAt(index)) }
    }

    fun cancelEdit() {
        if (!_uiState.value.saving) _uiState.update { it.copy(draft = null, message = null) }
    }

    fun save() {
        val draft = _uiState.value.draft ?: return
        submit(draft.mapIndexed { index, card -> DashboardCardUpdate(card.key, card.visible, index) })
    }

    fun reset() {
        if (_uiState.value.draft != null) submit(emptyList())
    }

    private fun changeDraft(change: (List<DashboardCard>) -> List<DashboardCard>) {
        if (_uiState.value.saving) return
        _uiState.update { state -> state.copy(draft = state.draft?.let(change), message = null) }
    }

    private fun submit(updates: List<DashboardCardUpdate>) {
        if (_uiState.value.saving) return
        val access = repository.dashboardAccess()
        val requestBinding = binding
        if (requestBinding == null || access?.binding != requestBinding || !access.canModify) {
            _uiState.update { it.copy(draft = null) }
            refresh()
            return
        }
        val request = ++generation
        _uiState.update { it.copy(saving = true, loading = false, message = null) }
        viewModelScope.launch {
            val result = repository.updateDashboardCards(requestBinding, updates)
            if (!isCurrent(request, requestBinding)) return@launch
            result.fold(
                onSuccess = { cards ->
                    _uiState.update {
                        it.copy(
                            cards = cards.items.sortedBy { card -> card.position }, draft = null, saving = false,
                            loadError = null, message = UiText.res(R.string.dashboard_saved), messageTone = MessageTone.Success,
                        )
                    }
                },
                onFailure = { error ->
                    _uiState.update {
                        it.copy(saving = false, message = error.toUiText(R.string.dashboard_save_failed), messageTone = MessageTone.Danger)
                    }
                },
            )
        }
    }

    private fun isCurrent(request: Int, requestBinding: LogicalSessionBinding): Boolean {
        if (generation != request) return false
        if (repository.dashboardAccess()?.binding == requestBinding) return true
        refresh()
        return false
    }
}
