package com.ticketbox.domain.model

/**
 * ADR-0030 background_tasks domain model.
 *
 * Status values mirror backend ``BackgroundTaskStatus``. We don't model
 * them as an enum yet because new task_types may add states without
 * breaking older clients — Kotlin sealed-class enforcement would force
 * a rebuild for every new state. String compares against the constants
 * below are deliberate.
 */
data class BackgroundTask(
    val publicId: String,
    val taskType: String,
    val status: String,
    val progressCurrent: Int,
    val progressTotal: Int?,
    val progressMessage: String?,
    val errorCode: String?,
    val errorMessage: String?,
    val createdAt: String,
    val startedAt: String?,
    val completedAt: String?,
    val cancellationRequestedAt: String?,
) {
    val isCancellable: Boolean
        get() = status in setOf(BACKGROUND_TASK_QUEUED, BACKGROUND_TASK_RUNNING) &&
            cancellationRequestedAt == null

    val isTerminal: Boolean
        get() = status in setOf(
            BACKGROUND_TASK_COMPLETED,
            BACKGROUND_TASK_FAILED,
            BACKGROUND_TASK_CANCELLED,
        )
}

const val BACKGROUND_TASK_QUEUED = "queued"
const val BACKGROUND_TASK_RUNNING = "running"
const val BACKGROUND_TASK_COMPLETED = "completed"
const val BACKGROUND_TASK_FAILED = "failed"
const val BACKGROUND_TASK_CANCELLED = "cancelled"

/** 任务 ``error_message`` 超过这个长度就当作不可直出的诊断串（正常中文短错误远短于此）。 */
const val BACKGROUND_TASK_ERROR_MAX_DISPLAY_LEN = 60

// 英文异常 / 堆栈特征：后端 error_message 可能是 ``str(exc)`` / "No handler …" /
// orphan 诊断串等英文技术文案，直出违反 §10（用户面不暴露底层异常）。命中任一即泛化。
private val BACKGROUND_TASK_ERROR_STACK_MARKERS = listOf(
    "Exception",
    "Traceback",
    "Error:",
    " at ",
    ".py",
    "java.",
    "org.",
    "com.",
    "app.",
)

/**
 * 8.3: 判定后端任务 ``error_message`` 是否应套泛化文案而非直出。
 *
 * 规则（保守，宁可泛化也不泄露技术串）——满足任一即泛化：
 * - 空白：无内容可展示。
 * - 含换行：多半是堆栈/多行诊断。
 * - 含英文异常/堆栈特征（见 [BACKGROUND_TASK_ERROR_STACK_MARKERS]）。
 * - 超长（> [BACKGROUND_TASK_ERROR_MAX_DISPLAY_LEN]）：正常中文短错误不会这么长。
 * - 不含任何中文：后端可直出的用户面错误都是我们自己写的中文短句；纯英文/符号串视为诊断。
 *
 * 否则（正常中文短消息）原样展示。纯函数，可单测。
 */
fun shouldGeneralizeTaskError(raw: String): Boolean {
    if (raw.isBlank()) return true
    if (raw.contains('\n')) return true
    if (raw.length > BACKGROUND_TASK_ERROR_MAX_DISPLAY_LEN) return true
    if (BACKGROUND_TASK_ERROR_STACK_MARKERS.any { raw.contains(it) }) return true
    return raw.none { it in '一'..'鿿' }
}
