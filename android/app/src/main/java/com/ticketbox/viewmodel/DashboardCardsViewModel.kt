package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DashboardCardsActions
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class DashboardCardsUiState(
    val cards: List<DashboardCard> = emptyList(),
    val loading: Boolean = false,
    val saving: Boolean = false,
    val canModify: Boolean = false,
    val dirty: Boolean = false,
    val savedRevision: Int = 0,
    val message: UiText? = null,
)

class DashboardCardsViewModel(
    private val repository: DashboardCardsActions,
) : ViewModel() {
    private var lastSavedCards: List<DashboardCard> = emptyList()
    private val _uiState = MutableStateFlow(DashboardCardsUiState(canModify = repository.canModifyLedger()))
    val uiState: StateFlow<DashboardCardsUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, canModify = repository.canModifyLedger(), message = null) }
            repository.dashboardCards(DashboardSurface.Android)
                .onSuccess { loaded ->
                    lastSavedCards = loaded.items.sortedDashboardCards().withSequentialPositions()
                    _uiState.update {
                        it.copy(
                            cards = lastSavedCards,
                            loading = false,
                            canModify = repository.canModifyLedger(),
                            dirty = false,
                        )
                    }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            canModify = repository.canModifyLedger(),
                            message = err.toUiText(R.string.dashboard_cards_load_failed),
                        )
                    }
                }
        }
    }

    fun moveCard(index: Int, delta: Int) {
        val current = _uiState.value.cards
        val target = index + delta
        if (target !in current.indices) return
        val mutable = current.toMutableList()
        val item = mutable.removeAt(index)
        mutable.add(target, item)
        applyDraft(mutable)
    }

    fun reorderCards(from: Int, to: Int) {
        val current = _uiState.value.cards
        if (from !in current.indices || to !in current.indices) return
        val mutable = current.toMutableList()
        val item = mutable.removeAt(from)
        mutable.add(to, item)
        applyDraft(mutable)
    }

    fun setVisible(key: String, visible: Boolean) {
        applyDraft(
            _uiState.value.cards.map { card ->
                if (card.key == key) card.copy(visible = visible) else card
            },
        )
    }

    fun saveCards() {
        val state = _uiState.value
        if (state.saving || state.cards.isEmpty()) return
        if (!repository.canModifyLedger()) {
            _uiState.update { it.copy(canModify = false, message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null) }
            repository.updateDashboardCards(
                updates = state.cards.toUpdates(),
                surface = DashboardSurface.Android,
            )
                .onSuccess { finishSaved(it.items, UiText.res(R.string.dashboard_cards_saved)) }
                .onFailure { err -> failSave(err) }
        }
    }

    fun resetCards() {
        val state = _uiState.value
        if (state.saving) return
        if (!repository.canModifyLedger()) {
            _uiState.update { it.copy(canModify = false, message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null) }
            repository.updateDashboardCards(emptyList(), DashboardSurface.Android)
                .onSuccess { finishSaved(it.items, UiText.res(R.string.dashboard_cards_reset_done)) }
                .onFailure { err -> failSave(err, R.string.dashboard_cards_reset_failed) }
        }
    }

    private fun applyDraft(updated: List<DashboardCard>) {
        val normalized = updated.withSequentialPositions()
        _uiState.update {
            it.copy(cards = normalized, dirty = normalized != lastSavedCards, message = null)
        }
    }

    private fun finishSaved(cards: List<DashboardCard>, message: UiText) {
        lastSavedCards = cards.sortedDashboardCards().withSequentialPositions()
        _uiState.update {
            it.copy(
                cards = lastSavedCards,
                saving = false,
                canModify = repository.canModifyLedger(),
                dirty = false,
                savedRevision = it.savedRevision + 1,
                message = message,
            )
        }
    }

    private fun failSave(err: Throwable, fallback: Int = R.string.dashboard_cards_save_failed) {
        _uiState.update {
            it.copy(
                saving = false,
                canModify = repository.canModifyLedger(),
                message = err.toUiText(fallback),
            )
        }
    }
}

private fun List<DashboardCard>.sortedDashboardCards(): List<DashboardCard> =
    sortedWith(compareBy<DashboardCard> { it.position }.thenBy { it.key })

private fun List<DashboardCard>.withSequentialPositions(): List<DashboardCard> =
    mapIndexed { index, card -> card.copy(position = index) }

private fun List<DashboardCard>.toUpdates(): List<DashboardCardUpdate> =
    withSequentialPositions().mapIndexed { index, card ->
        DashboardCardUpdate(key = card.key, visible = card.visible, position = index)
    }
