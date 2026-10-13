package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.remote.dto.SavedViewDto
import com.ticketbox.data.remote.dto.SavedViewResultsDto
import com.ticketbox.data.repository.SavedQueryRepository
import com.ticketbox.data.repository.TagActions
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class SavedQueryUiState(
    val catalog: List<SavedViewDto>? = null,
    val tags: List<ManagedTag> = emptyList(),
    val tagError: UiText? = null,
    val selectedId: String? = null,
    val results: SavedViewResultsDto? = null,
    val loading: Boolean = false,
    val error: UiText? = null,
)

class SavedQueryViewModel(
    private val repository: SavedQueryRepository,
    private val tags: TagActions,
) : ViewModel() {
    private val owner = repository.captureBinding()
    private val _state = MutableStateFlow(SavedQueryUiState())
    val state = _state.asStateFlow()
    val drafts = SavedQueryDraftController(repository, viewModelScope) { refresh() }
    private var readRevision = 0

    init {
        viewModelScope.launch {
            repository.observeAccess().collect { access ->
                readRevision++
                _state.value = SavedQueryUiState()
                if (access != null && owner?.sameReferenceOwner(access.binding) == true) refresh()
            }
        }
    }

    fun refresh() {
        val binding = repository.captureBinding() ?: return
        if (owner?.sameReferenceOwner(binding) != true) return
        val revision = ++readRevision
        _state.value = _state.value.copy(loading = true, error = null)
        viewModelScope.launch {
            val catalog = repository.catalog(binding)
            val tagResult = tags.tags(binding)
            if (revision != readRevision) return@launch
            _state.value = _state.value.copy(catalog = catalog.getOrNull(), tags = tagResult.getOrDefault(emptyList()),
                loading = false, error = catalog.exceptionOrNull()?.queryReadError(),
                tagError = tagResult.exceptionOrNull()?.queryReadError())
            _state.value.selectedId?.let { open(it, _state.value.results?.page ?: 1) }
        }
    }

    fun open(publicId: String, page: Int = 1) {
        val binding = repository.captureBinding() ?: return
        if (owner?.sameReferenceOwner(binding) != true) return
        val revision = ++readRevision
        _state.value = _state.value.copy(selectedId = publicId, results = null, loading = true, error = null)
        viewModelScope.launch {
            val result = repository.results(binding, publicId, page)
            if (revision == readRevision) _state.value = _state.value.copy(results = result.getOrNull(), loading = false,
                error = result.exceptionOrNull()?.queryReadError())
        }
    }

    fun closeResults() {
        readRevision++
        _state.value = _state.value.copy(selectedId = null, results = null, loading = false, error = null)
        refresh()
    }
}

private fun Throwable.queryReadError(): UiText = message?.let(UiText::raw) ?: UiText.res(R.string.saved_query_read_failed)
