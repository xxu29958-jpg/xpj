package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.CategoryPreferenceActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CategoryPreference
import com.ticketbox.domain.model.CategoryPreferenceInspection
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job

data class CategoryDirectoryUiState(
    val customCategories: List<CategoryPreference> = emptyList(),
    val loading: Boolean = false,
    val loadFailed: Boolean = false,
    val busyCategoryId: String? = null,
    val canModify: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val changedRevision: Int = 0,
    val inspectingCategory: CategoryPreference? = null,
    val inspection: CategoryPreferenceInspection? = null,
    val inspectionLoading: Boolean = false,
    val inspectionError: UiText? = null,
)

class CategoryDirectoryViewModel(
    private val repository: CategoryPreferenceActions,
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        CategoryDirectoryUiState(canModify = repository.canModifyLedger()),
    )
    val uiState: StateFlow<CategoryDirectoryUiState> = _uiState.asStateFlow()
    private var inspectionJob: Job? = null

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    loading = true,
                    loadFailed = false,
                    message = null,
                    messageTone = MessageTone.Neutral,
                    canModify = repository.canModifyLedger(),
                )
            }
            repository.categoryPreferences()
                .onSuccess { categories ->
                    _uiState.update {
                        it.copy(
                            customCategories = categories.sortedWith(
                                compareByDescending(CategoryPreference::usageCount)
                                    .thenBy(CategoryPreference::name),
                            ),
                            loading = false,
                            loadFailed = false,
                            canModify = repository.canModifyLedger(),
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            loading = false,
                            loadFailed = true,
                            canModify = repository.canModifyLedger(),
                            message = error.toUiText(R.string.category_directory_load_failed),
                            messageTone = MessageTone.Danger,
                        )
                    }
                }
        }
    }

    fun inspect(category: CategoryPreference) {
        inspectionJob?.cancel()
        _uiState.update { it.copy(inspectingCategory = category, inspection = null,
            inspectionLoading = true, inspectionError = null) }
        inspectionJob = viewModelScope.launch {
            repository.inspectCategoryPreference(category.publicId)
                .onSuccess { inspection ->
                    _uiState.update { it.copy(inspection = inspection, inspectingCategory = inspection.category,
                        inspectionLoading = false, canModify = repository.canModifyLedger()) }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(inspectionLoading = false,
                        inspectionError = error.toUiText(R.string.category_directory_inspection_failed)) }
                }
        }
    }

    fun dismissInspection() {
        inspectionJob?.cancel()
        _uiState.update { it.copy(inspectingCategory = null, inspection = null,
            inspectionLoading = false, inspectionError = null) }
    }

    fun delete(category: CategoryPreference) {
        if (_uiState.value.busyCategoryId != null || !repository.canModifyLedger()) return
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    busyCategoryId = category.publicId,
                    message = null,
                    inspectionError = null,
                    messageTone = MessageTone.Neutral,
                )
            }
            repository.deleteCategoryPreference(category.publicId, category.rowVersion)
                .onSuccess {
                    _uiState.update {
                        it.copy(
                            customCategories = it.customCategories.filterNot { item ->
                                item.publicId == category.publicId
                            },
                            busyCategoryId = null,
                            message = UiText.res(R.string.category_directory_deleted, category.name),
                            messageTone = MessageTone.Success,
                            changedRevision = it.changedRevision + 1,
                            inspectingCategory = null,
                            inspection = null,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(
                            busyCategoryId = null,
                            message = error.toUiText(R.string.category_directory_delete_failed),
                            messageTone = MessageTone.Danger,
                            inspectionError = error.toUiText(R.string.category_directory_delete_failed),
                            inspection = (error as? RepositoryException)?.conflict?.categoryReferences
                                ?.takeIf { references -> references.isNotEmpty() }
                                ?.let { references -> CategoryPreferenceInspection(category, references) }
                                ?: it.inspection,
                        )
                    }
                }
        }
    }
}
