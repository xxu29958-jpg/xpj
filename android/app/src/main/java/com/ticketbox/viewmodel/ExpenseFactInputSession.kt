package com.ticketbox.viewmodel

import com.ticketbox.data.repository.ExpenseFactInputActions
import com.ticketbox.data.repository.ExpenseFactOriginalInput
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Ordered local writes finish across navigation; no network or command dispatch runs in this lifetime. */
internal class ExpenseFactInputSession(
    val binding: LogicalSessionBinding,
    private val expenseId: Long,
    private val repository: ExpenseFactInputActions,
    private val scope: CoroutineScope,
    originals: List<ExpenseFactOriginalInput>,
    private val onChanged: () -> Unit,
) {
    private val saved = originals.associateBy { it.formKey }.toMutableMap()
    private val planned = saved.toMutableMap()
    private var tail: Job? = null
    private val failures = mutableMapOf<String, Throwable>()
    private var pendingWrites = 0
    val writing: Boolean get() = pendingWrites > 0
    val error: Throwable? get() = failures.values.firstOrNull()
    val keys: Set<String> get() = planned.keys.toSet()
    fun original(key: String) = planned[key]
    fun draft(key: String) = original(key)?.let { ExpenseFactInputCodec.decode(it.json, expenseId) }

    fun keep(key: String, draft: ExpenseFactInputDraft, review: Boolean = false) {
        val previous = planned[key]
        if (!review && previous != null && previous.binding != binding) {
            failures[key] = RepositoryException("连接身份已变化，原输入仍保留，请明确核对后再继续。")
            onChanged()
            return
        }
        val next = ExpenseFactOriginalInput(binding, expenseId, key,
            if (review || previous == null) UUID.randomUUID().toString() else previous.originalKey, ExpenseFactInputCodec.encode(draft))
        planned[key] = next
        if (next == saved[key]) { failures.remove(key); onChanged(); return }
        pendingWrites++
        onChanged()
        val pending = tail
        tail = scope.launch(start = CoroutineStart.UNDISPATCHED) {
            withContext(NonCancellable) {
                pending?.join()
                val result = repository.saveFactInput(saved[key], next)
                result.onSuccess { saved[key] = next; failures.remove(key) }
                    .onFailure { failures[key] = it }
                pendingWrites--
                onChanged()
            }
        }
    }

    suspend fun ready(key: String): Result<ExpenseFactOriginalInput> {
        tail?.join()
        val input = planned[key]
        return if (input != null && saved[key] == input && input.binding == binding) Result.success(input)
        else Result.failure(failures[key] ?: RepositoryException("原输入尚未保存，请重试保存后继续。"))
    }

    suspend fun flush(): Result<Unit> {
        tail?.join()
        return if (planned == saved) Result.success(Unit)
        else Result.failure(error ?: RepositoryException("原输入尚未保存，请重试保存后离开。"))
    }

    fun retry() {
        keys.filter { planned[it] != saved[it] }.forEach { key -> draft(key)?.let { keep(key, it) } }
    }

    suspend fun discard(key: String): Result<Unit> {
        tail?.join()
        val input = saved[key]
        val result = if (input == null) Result.success(Unit) else repository.discardFactInput(binding, input)
        result.onSuccess { forget(key) }
        result.exceptionOrNull()?.let { failures[key] = it }
        onChanged()
        return result
    }

    fun forget(key: String) { saved.remove(key); planned.remove(key); failures.remove(key); onChanged() }
}
