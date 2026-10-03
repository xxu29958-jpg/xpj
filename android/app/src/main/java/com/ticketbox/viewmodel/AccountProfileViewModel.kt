package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.AccountProfile
import com.ticketbox.data.repository.AccountProfileActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class AccountProfileUiState(
    val profile: AccountProfile? = null,
    val name: String = "",
    val busy: Boolean = false,
    val fresh: Boolean = false,
    val message: UiText? = null,
    val tone: MessageTone = MessageTone.Neutral,
)

class AccountProfileViewModel(private val repository: AccountProfileActions) : ViewModel() {
    private val binding = repository.currentBinding()
    private val state = MutableStateFlow(AccountProfileUiState())
    val uiState = state.asStateFlow()

    fun changeName(name: String) {
        if (!state.value.busy) state.update { it.copy(name = name.take(120), message = null) }
    }

    fun refresh() {
        val captured = binding ?: return
        if (state.value.busy) return
        state.update { it.copy(busy = true, message = null) }
        viewModelScope.launch {
            repository.read(captured).onSuccess { profile ->
                state.update { it.copy(profile = profile, fresh = true,
                    name = if (it.profile == null || it.name == it.profile.displayName) profile.displayName else it.name) }
            }.onFailure { failure ->
                state.update { it.copy(fresh = false, message = failure.toUiText(R.string.account_profile_load_failed), tone = MessageTone.Danger) }
            }
            state.update { it.copy(busy = false) }
        }
    }

    fun save() {
        val captured = binding ?: return
        val before = state.value
        val profile = before.profile ?: return
        if (before.busy || !before.fresh || before.name.isBlank()) return
        state.update { it.copy(busy = true, message = null) }
        viewModelScope.launch {
            repository.rename(captured, before.name, profile.displayName).onSuccess { saved ->
                state.update { it.copy(profile = saved, name = saved.displayName, fresh = true,
                    message = UiText.res(R.string.account_profile_saved), tone = MessageTone.Success) }
            }.onFailure { failure ->
                if ((failure as? RepositoryException)?.httpStatusCode == 409) {
                    // Never silently resubmit. Show the new baseline beside the retained input.
                    val current = repository.read(captured).getOrNull()
                    state.update { it.copy(profile = current ?: it.profile, fresh = current != null,
                        message = UiText.res(if (current != null) R.string.account_profile_conflict else R.string.account_profile_conflict_reload),
                        tone = MessageTone.Danger) }
                } else {
                    state.update { it.copy(message = failure.toUiText(R.string.account_profile_save_failed), tone = MessageTone.Danger) }
                }
            }
            state.update { it.copy(busy = false) }
        }
    }
}
