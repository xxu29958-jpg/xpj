package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.repository.CategoryPreferenceActions

@Suppress("UNCHECKED_CAST")
fun categoryDirectoryViewModelFactory(
    repository: CategoryPreferenceActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T =
        CategoryDirectoryViewModel(repository) as T
}
