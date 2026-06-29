package com.ticketbox.domain.model

/**
 * v1.1 user-declared monthly income line. Drives the income leg of
 * "本月可自由支配".
 */
data class IncomePlan(
    val publicId: String,
    val label: String,
    val sourceType: IncomeSourceType,
    val frequency: IncomeFrequency,
    val incomeMonth: String?,
    val amountCents: Long,
    val payDay: Int,
    val status: IncomePlanStatus,
    val createdAt: String,
    val updatedAt: String,
    val rowVersion: Long,
    val archivedAt: String?,
) {
    val isActive: Boolean get() = status == IncomePlanStatus.ACTIVE
    val isArchived: Boolean get() = status == IncomePlanStatus.ARCHIVED
}

enum class IncomeFrequency(val wireValue: String, val displayName: String) {
    MONTHLY("monthly", "每月固定"),
    ONE_TIME("one_time", "实际到账"),
    ;

    companion object {
        fun fromWire(value: String?): IncomeFrequency =
            entries.firstOrNull { it.wireValue.equals(value, ignoreCase = true) }
                ?: MONTHLY
    }
}

/**
 * Coarse classifier the user picks during add. Free-form text would
 * leak inconsistent values to the AI advisor (`source_type` is on the
 * ADR-0036 allowed-fields list); a small enum keeps the surface stable.
 */
enum class IncomeSourceType(val wireValue: String, val displayName: String) {
    SALARY("salary", "工资"),
    BONUS("bonus", "奖金"),
    FREELANCE("freelance", "副业 / 接单"),
    RENTAL("rental", "租金"),
    OTHER("other", "其它"),
    ;

    companion object {
        fun fromWire(value: String?): IncomeSourceType =
            entries.firstOrNull { it.wireValue.equals(value, ignoreCase = true) }
                ?: OTHER
    }
}

enum class IncomePlanStatus(val wireValue: String) {
    ACTIVE("active"),
    ARCHIVED("archived"),
    ;

    companion object {
        fun fromWire(value: String?): IncomePlanStatus =
            entries.firstOrNull { it.wireValue.equals(value, ignoreCase = true) } ?: ACTIVE
    }
}

/** Pay-day must be 1..31 per the backend CHECK constraint. Surface a
 * Kotlin-level guard so the UI form catches it before round-tripping. */
fun Int.isValidPayDay(): Boolean = this in 1..31
