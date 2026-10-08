package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto

internal const val RULE_APPLICATION_TARGET = "rule_application:confirmed"
internal const val RULE_APPLICATION_UNVERIFIED = "rule_application_receipt_unverified"
internal const val RULE_APPLICATION_READ_REFRESH = "rule_application_read_refresh_required"

@JsonClass(generateAdapter = true)
data class RuleApplicationPayload(
    val version: Int = 1,
    val previewToken: String,
    val maxScan: Int,
    val scanned: Int,
    val expectedChanges: Int,
) {
    fun supports(row: OutboxRow): Boolean = version == 1 && row.type == PendingMutationType.ApplyConfirmedRules &&
        row.targetId == RULE_APPLICATION_TARGET && row.expectedRowVersion == 0L && !row.idempotencyKey.isNullOrBlank() &&
        previewToken.isNotBlank() && maxScan in 1..1000 && scanned in 1..maxScan && expectedChanges in 1..scanned

    fun accepts(row: OutboxRow, receipt: RuleApplyConfirmedResponseDto): Boolean = supports(row) && !receipt.dryRun &&
        receipt.commandKey == row.idempotencyKey && receipt.confirmedScanned == scanned && receipt.scanLimit == maxScan &&
        receipt.changedCount in 0..expectedChanges &&
        (if (receipt.changedCount == 0) receipt.applicationPublicId == null else !receipt.applicationPublicId.isNullOrBlank())
}

data class PendingRuleApplication(
    val row: OutboxRow,
    val original: RuleApplicationPayload?,
    val receipt: RuleApplyConfirmedResponseDto?,
) {
    val supported: Boolean get() = original?.supports(row) == true
    val isDone: Boolean get() = row.status == PendingMutationStatus.Done
    val needsRefresh: Boolean get() = row.requiresRuleApplicationRefresh()
    val canRetry: Boolean get() = supported && row.status == PendingMutationStatus.Failed &&
        (row.lastError?.startsWith("max_attempts_exceeded(") == true || row.lastError in setOf(
            "client_upgrade_required", "runtime_version_mismatch", RULE_APPLICATION_UNVERIFIED))
    val canDrop: Boolean get() = row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)
}

internal fun OutboxRow.requiresRuleApplicationRefresh(): Boolean = type == PendingMutationType.ApplyConfirmedRules &&
    status == PendingMutationStatus.Done && lastError == RULE_APPLICATION_READ_REFRESH && receiptJson != null
