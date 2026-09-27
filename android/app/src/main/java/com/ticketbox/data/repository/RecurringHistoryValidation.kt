package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RecurringDefinitionDto
import com.ticketbox.data.remote.dto.RecurringHistoryPageDto
import java.time.Instant
import java.time.LocalDate

internal fun RecurringHistoryPageDto.validateHistory(binding: LogicalSessionBinding, id: String, before: Long?) {
    require(ledgerId == binding.ledgerId && publicId == id) { "固定支出历史所属账本不匹配。" }
    val versions = items.map { it.rowVersion }
    require(items.size <= 50 && versions.all { it > 0 && (before == null || it < before) } &&
        versions.zipWithNext().all { (a, b) -> a > b }) { "固定支出历史顺序不正确。" }
    require(nextBeforeVersion == null || versions.lastOrNull() == nextBeforeVersion) { "固定支出历史分页不正确。" }
    items.forEach {
        Instant.parse(it.recordedAt)
        require(it.changeKind in setOf("baseline", "create", "edit", "pause", "resume", "archive", "restore")) {
            "固定支出历史变更无法识别。"
        }
        it.snapshot.validateDefinition()
    }
}

internal fun RecurringDefinitionDto.validateDefinition() {
    require(merchant.isNotBlank() && merchantKey.isNotBlank() && frequency == "monthly" && baselineAmountCents >= 0 &&
        status in setOf("active", "paused", "archived") && source.isNotBlank()) { "固定支出历史定义不正确。" }
    nextExpectedDate?.let { LocalDate.parse(it) }
}
