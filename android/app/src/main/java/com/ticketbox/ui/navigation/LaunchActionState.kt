package com.ticketbox.ui.navigation

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.referentialEqualityPolicy
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.setValue
import com.ticketbox.data.repository.LogicalSessionBinding

/**
 * 系统分享 / 启动器 shortcut 经 MainShell 派发给具体 Route 的一次性入口动作（W1）。
 * 每个变体由对应 Route 负责消费：
 *  - [UploadSharedImages] / [OpenImagePicker] → PendingRoute。
 *  - [OpenManualEntry] → 账本页（LedgerScreen 的记一笔表单）。
 */
internal sealed interface LaunchAction {
    /** One immutable selection; another share or picker result has another original batch id. */
    data class UploadSharedImages(val selection: LaunchIntentRequest.ShareImages) : LaunchAction

    /** 「传小票」shortcut：拉起系统图片选择。 */
    object OpenImagePicker : LaunchAction

    /** 「记一笔」shortcut：打开手动记账表单。 */
    object OpenManualEntry : LaunchAction
}

/**
 * Pre-acceptance handoff only. Room owns every accepted upload and all delivery/recovery state.
 * A failed or interrupted acceptance retains the same selection until an explicit retry or cancel.
 * The saveable snapshot also keeps picker selections when their Activity is recreated.
 */
internal class LaunchActionState {
    private var actions by mutableStateOf<List<LaunchAction>>(emptyList(), referentialEqualityPolicy())
    private var acceptingId by mutableStateOf<String?>(null)
    private var retryId by mutableStateOf<String?>(null)
    var uploadAttempt by mutableStateOf(0)
        private set

    val pending: LaunchAction? get() = actions.firstOrNull()
    val pendingUpload: LaunchAction.UploadSharedImages? get() = pending as? LaunchAction.UploadSharedImages
    val acceptingUpload: Boolean get() = acceptingId != null
    val awaitingUploadRetry: Boolean get() = retryId != null && retryId == pendingUpload?.selection?.batchId

    fun post(action: LaunchAction) {
        if (action is LaunchAction.UploadSharedImages) {
            val index = actions.indexOfFirst { it is LaunchAction.UploadSharedImages && it.selection.batchId == action.selection.batchId }
            if (index < 0) {
                actions = actions + action
            } else {
                val previous = actions[index] as LaunchAction.UploadSharedImages
                check(previous.selection.uris == action.selection.uris) { "Original upload selection changed" }
                check(action.selection.expectedBinding == null || previous.selection.expectedBinding == null ||
                    action.selection.expectedBinding == previous.selection.expectedBinding) { "Original upload binding changed" }
                previous.selection.expectedBinding?.let(action.selection::freezeBinding)
                actions = actions.toMutableList().apply { this[index] = action }
            }
        } else {
            actions = listOf(action) + actions.filterIsInstance<LaunchAction.UploadSharedImages>()
        }
    }

    /** Remove one exact action; later shares never become an appended prefix of that original. */
    fun consume(accepted: LaunchAction? = pending): LaunchAction? {
        val index = actions.indexOf(accepted)
        if (index < 0) return null
        actions = actions.filterIndexed { position, _ -> position != index }
        if (accepted is LaunchAction.UploadSharedImages && retryId == accepted.selection.batchId) retryId = null
        return accepted
    }

    fun containsUpload(batchId: String): Boolean = actions.any {
        it is LaunchAction.UploadSharedImages && it.selection.batchId == batchId
    }

    fun beginUpload(action: LaunchAction.UploadSharedImages, binding: LogicalSessionBinding): Boolean {
        val current = pendingUpload ?: return false
        if (current.selection.batchId != action.selection.batchId || acceptingUpload || awaitingUploadRetry) return false
        val originalBinding = current.selection.freezeBinding(binding)
        action.selection.freezeBinding(originalBinding)
        acceptingId = current.selection.batchId
        return true
    }

    fun finishUpload(action: LaunchAction.UploadSharedImages, accepted: Boolean) {
        if (acceptingId != action.selection.batchId) return
        acceptingId = null
        if (accepted) consume(action) else retryId = action.selection.batchId
    }

    fun retryUpload() {
        if (acceptingUpload || pendingUpload == null) return
        retryId = null
        uploadAttempt++
    }

    fun cancelUploadSelection() {
        if (!acceptingUpload) pendingUpload?.let(::consume)
    }

    fun snapshot(): List<ArrayList<String>> = listOf(arrayListOf("state", acceptingId ?: retryId.orEmpty())) + actions.map {
        when (it) {
            is LaunchAction.UploadSharedImages -> it.selection.savedFields()
            LaunchAction.OpenImagePicker -> arrayListOf("picker")
            LaunchAction.OpenManualEntry -> arrayListOf("manual")
        }
    }

    companion object {
        val Saver = listSaver<LaunchActionState, ArrayList<String>>(save = { it.snapshot() }, restore = ::restore)

        fun restore(snapshot: List<List<String>>): LaunchActionState = LaunchActionState().apply {
            retryId = snapshot.first()[1].ifEmpty { null }
            actions = snapshot.drop(1).map { fields -> when (fields.first()) {
                "picker" -> LaunchAction.OpenImagePicker
                "manual" -> LaunchAction.OpenManualEntry
                else -> LaunchAction.UploadSharedImages(restoreLaunchRequest(fields) as LaunchIntentRequest.ShareImages)
            } }
        }
    }
}
