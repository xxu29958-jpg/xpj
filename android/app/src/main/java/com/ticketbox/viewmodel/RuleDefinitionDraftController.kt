package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RuleDefinitionDraft
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleDraftForm
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class RuleDefinitionDraftState(
    val binding: LogicalSessionBinding? = null,
    val drafts: List<RuleDefinitionDraft> = emptyList(),
    val selectedKey: String? = null,
    val ready: Boolean = false,
    val canModify: Boolean = false,
    val busy: Boolean = false,
    val error: UiText? = null,
) {
    val selected: RuleDefinitionDraft? get() = drafts.find { it.key == selectedKey }
}

/** Owns unsent input only. Room atomically hands it to the existing rule Outbox on submission. */
class RuleDefinitionDraftController(
    private val repository: RuleRepository,
    private val scope: CoroutineScope,
    private val onSubmitted: (Long) -> Unit,
) {
    private val _state = MutableStateFlow(RuleDefinitionDraftState())
    val state = _state.asStateFlow()

    init {
        scope.launch {
            repository.observeAccess().collect { access ->
                if (_state.value.binding != access?.binding) {
                    _state.value = RuleDefinitionDraftState(binding = access?.binding, canModify = access?.canModify == true)
                    read()
                } else _state.value = _state.value.copy(canModify = access?.canModify == true)
            }
        }
    }

    fun reload() { scope.launch { read() } }

    private suspend fun read() {
        val binding = _state.value.binding ?: return
        val result = runCatching { requireNotNull(repository.definitionInputs).read(binding) }
        if (repository.currentAccess()?.binding != binding) return
        val retained = _state.value.drafts
        val loaded = result.getOrNull()?.filterNot { row -> retained.any { it.slot == row.slot } }.orEmpty()
        _state.value = _state.value.copy(drafts = retained + loaded, ready = _state.value.ready || result.isSuccess,
            error = if (result.isFailure) UiText.res(R.string.category_rule_draft_read_failed) else null)
    }

    fun begin(form: CategoryRuleDraftForm) {
        val current = _state.value
        val binding = current.binding ?: return
        if (!current.ready || !current.canModify || current.busy) return
        val draft = current.drafts.find { it.baseline?.id == form.editingRule?.id }
            ?: form.toDraft(binding, UUID.randomUUID().toString())
        _state.value = current.copy(selectedKey = draft.key)
        if (draft !in current.drafts) change(draft)
    }

    fun open(draft: RuleDefinitionDraft) {
        if (!_state.value.busy && draft in _state.value.drafts) _state.value = _state.value.copy(selectedKey = draft.key)
    }

    fun close() { _state.value = _state.value.copy(selectedKey = null) }

    fun change(draft: RuleDefinitionDraft) {
        val current = _state.value
        if (!current.canModify || current.busy || draft.binding != current.binding || draft.key != current.selectedKey) return
        publish(draft)
        // Finish only local input writes when the route is popped; no network operation is shielded.
        scope.launch(start = CoroutineStart.UNDISPATCHED) { withContext(NonCancellable) { persist(draft) } }
    }

    fun reviewBinding() {
        val draft = _state.value.selected ?: return
        val current = _state.value.binding ?: return
        if (draft.binding.serverUrl == current.serverUrl && draft.binding.ownerKey == current.ownerKey &&
            draft.binding.ledgerId == current.ledgerId) change(draft.copy(binding = current))
    }

    private fun publish(draft: RuleDefinitionDraft) {
        _state.value = _state.value.copy(drafts = _state.value.drafts.filterNot { it.slot == draft.slot } + draft, error = null)
    }

    private suspend fun persist(draft: RuleDefinitionDraft): Boolean {
        val result = runCatching { requireNotNull(repository.definitionInputs).write(draft) }
        if (result.isFailure && _state.value.binding == draft.binding) {
            _state.value = _state.value.copy(error = UiText.res(R.string.category_rule_draft_save_failed))
        }
        return result.isSuccess
    }

    fun submit(draft: RuleDefinitionDraft, request: CategoryRuleRequest) {
        val current = _state.value
        if (!current.canModify || current.busy || draft.binding != current.binding || draft !in current.drafts) return
        _state.value = current.copy(busy = true, error = null)
        scope.launch {
            if (persist(draft)) {
                val result = draft.baseline?.let { repository.updateCategoryRule(draft.binding, it, request, draft) }
                    ?: repository.createCategoryRule(draft.binding, request, draft)
                if (_state.value.binding == draft.binding) finish(draft, result)
            }
            if (_state.value.binding == draft.binding) _state.value = _state.value.copy(busy = false)
        }
    }

    private fun finish(draft: RuleDefinitionDraft, result: Result<Long>) {
        result.onSuccess { id ->
            _state.value = _state.value.copy(drafts = _state.value.drafts.filterNot { it.key == draft.key }, selectedKey = null)
            onSubmitted(id)
        }.onFailure { error -> _state.value = _state.value.copy(error = error.toUiText(R.string.category_rules_save_failed)) }
    }
}
