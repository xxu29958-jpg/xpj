package com.ticketbox.notification

import com.ticketbox.data.repository.LogicalSessionBinding
import java.time.LocalDate
import java.time.YearMonth

/** A route back to an original task, never a credential or permission to read it. */
data class NotificationTask(val binding: LogicalSessionBinding, val destination: NotificationDestination)

sealed interface NotificationDestination {
    data class Expense(val id: Long) : NotificationDestination
    data class Repayment(val publicId: String) : NotificationDestination
    data class Recurring(val publicId: String, val expectedDate: String) : NotificationDestination
    data class Budget(val month: String) : NotificationDestination
    data object Backup : NotificationDestination
}

internal const val ACTION_NOTIFICATION_TASK = "com.ticketbox.action.NOTIFICATION_TASK"
internal const val EXTRA_NOTIFICATION_TASK = "com.ticketbox.notification.task"

/** Token renewal is allowed; a different server, data generation, account or device is not. */
internal fun NotificationTask.belongsTo(current: LogicalSessionBinding?): Boolean = current != null &&
    current.serverUrl == binding.serverUrl && current.ownerKey == binding.ownerKey &&
    (destination == NotificationDestination.Backup || current.ledgerId == binding.ledgerId)

internal fun NotificationTask.savedFields(): ArrayList<String> = arrayListOf(
    "v1", binding.serverUrl, binding.ledgerId, binding.ownerKey, binding.sessionGeneration, binding.bindingRevision,
).apply {
    addAll(when (val target = destination) {
        is NotificationDestination.Expense -> listOf("expense", target.id.toString())
        is NotificationDestination.Repayment -> listOf("repayment", target.publicId)
        is NotificationDestination.Recurring -> listOf("recurring", target.publicId, target.expectedDate)
        is NotificationDestination.Budget -> listOf("budget", target.month)
        NotificationDestination.Backup -> listOf("backup")
    })
}

internal fun NotificationTask.intentIdentity(): String = boundReminderKey(binding,
    listOf(binding.ledgerId.takeUnless { destination == NotificationDestination.Backup }.orEmpty())
        .plus(savedFields().drop(TASK_HEADER_SIZE)).joinToString("\u0000"))

internal fun readNotificationTask(fields: List<String>): NotificationTask? = runCatching {
    require(fields.size > TASK_HEADER_SIZE && fields[0] == "v1")
    require(listOf(fields[1], fields[3], fields[4], fields[5]).all { it.isNotBlank() })
    val binding = LogicalSessionBinding(fields[1], fields[2], fields[3], fields[4], fields[5])
    val destination = readNotificationDestination(fields.drop(TASK_HEADER_SIZE))
    require(destination == NotificationDestination.Backup || binding.ledgerId.isNotBlank())
    NotificationTask(binding, destination)
}.getOrNull()

private fun readNotificationDestination(fields: List<String>): NotificationDestination = when (fields.first()) {
    "expense" -> {
        require(fields.size == 2)
        NotificationDestination.Expense(fields[1].toLong().also { require(it > 0) })
    }
    "repayment" -> {
        require(fields.size == 2)
        NotificationDestination.Repayment(taskPublicId(fields[1]))
    }
    "recurring" -> {
        require(fields.size == 3)
        NotificationDestination.Recurring(taskPublicId(fields[1]), LocalDate.parse(fields[2]).toString())
    }
    "budget" -> {
        require(fields.size == 2)
        NotificationDestination.Budget(YearMonth.parse(fields[1]).toString())
    }
    "backup" -> {
        require(fields.size == 1)
        NotificationDestination.Backup
    }
    else -> error("Unknown notification task")
}

private fun taskPublicId(value: String): String = value.also {
    require(it.isNotBlank() && it.length <= MAX_TASK_ID_LENGTH && '\u0000' !in it)
}

private const val TASK_HEADER_SIZE = 6
private const val MAX_TASK_ID_LENGTH = 128
