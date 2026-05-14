package com.ticketbox.domain.model

data class Expense(
    val id: Long,
    val publicId: String,
    val amountCents: Long?,
    val merchant: String?,
    val category: String,
    val note: String?,
    val source: String,
    val imagePath: String?,
    val thumbnailPath: String?,
    val imageHash: String?,
    val rawText: String?,
    val confidence: Double?,
    val duplicateStatus: String,
    val duplicateOfId: Long?,
    val duplicateReason: String?,
    val tags: String?,
    val valueScore: Int?,
    val regretScore: Int?,
    val status: String,
    val expenseTime: String?,
    val createdAt: String,
    val updatedAt: String,
    val confirmedAt: String?,
    val rejectedAt: String?,
)

data class ExpenseDraft(
    val amountCents: Long?,
    val merchant: String?,
    val category: String?,
    val note: String?,
    val expenseTime: String?,
    val tags: String?,
    val valueScore: Int?,
    val regretScore: Int?,
)

data class ExpenseItem(
    val publicId: String,
    val position: Int,
    val name: String,
    val quantityText: String?,
    val unitPriceCents: Long?,
    val amountCents: Long?,
    val category: String,
    val rawText: String?,
    val confidence: Double?,
    val isOcrDraft: Boolean,
    val createdAt: String,
    val updatedAt: String,
)

data class ExpenseItems(
    val expenseId: Long,
    val parentAmountCents: Long?,
    val itemsTotalAmountCents: Long?,
    val mismatchCents: Long?,
    val items: List<ExpenseItem>,
) {
    val hasMismatch: Boolean
        get() = mismatchCents != null && mismatchCents != 0L
}

data class ExpenseItemDraft(
    val name: String,
    val quantityText: String?,
    val unitPriceCents: Long?,
    val amountCents: Long?,
    val category: String?,
    val rawText: String?,
    val confidence: Double?,
)

data class ExpenseSplit(
    val publicId: String,
    val position: Int,
    val memberId: Long,
    val accountName: String,
    val role: String,
    val amountCents: Long,
    val note: String?,
    val disabledAt: String?,
    val createdAt: String,
    val updatedAt: String,
) {
    val isDisabledMember: Boolean
        get() = !disabledAt.isNullOrBlank()
}

data class ExpenseSplits(
    val expenseId: Long,
    val parentAmountCents: Long?,
    val splitsTotalAmountCents: Long?,
    val mismatchCents: Long?,
    val splits: List<ExpenseSplit>,
) {
    val hasMismatch: Boolean
        get() = mismatchCents != null && mismatchCents != 0L
}

data class ExpenseSplitDraft(
    val memberId: Long,
    val amountCents: Long,
    val note: String?,
)

enum class NotificationDraftSource(val apiValue: String) {
    WeChat("wechat"),
    Alipay("alipay"),
    BankSms("bank_sms"),
    BankApp("bank_app"),
    Other("other"),
}

data class NotificationDraft(
    val source: NotificationDraftSource,
    val amountCents: Long?,
    val merchant: String?,
    val category: String?,
    val expenseTime: String?,
)

data class CategoryStats(
    val category: String,
    val amountCents: Long,
    val count: Int,
)

data class TagStats(
    val tag: String,
    val amountCents: Long,
    val count: Int,
)

data class CategoryInsight(
    val topCategory: String,
    val topAmountCents: Long,
    val topSharePercent: Int,
    val averagePerExpenseCents: Long,
    val categoryCount: Int,
    val isConcentrated: Boolean,
)

data class MonthlyStats(
    val month: String,
    val totalAmountCents: Long,
    val count: Int,
    val byCategory: List<CategoryStats>,
    val byTag: List<TagStats> = emptyList(),
)

data class FrequentMerchant(
    val merchant: String,
    val count: Int,
)

data class RecurringCandidate(
    val merchant: String,
    val amountCents: Long,
    val occurrenceCount: Int,
    val lastSeenAt: String?,
    val confidence: String,
    val reason: String,
)

data class DataQualitySummary(
    val pendingTotal: Int,
    val missingAmount: Int,
    val missingMerchant: Int,
    val missingCategory: Int,
    val suspectedDuplicates: Int,
    val confirmedWithoutImage: Int,
    val readyToConfirm: Int,
    val oldestPendingAgeDays: Int?,
    val generatedAt: String,
)

data class DailySpend(
    val date: String,
    val label: String,
    val amountCents: Long,
)

data class MonthComparison(
    val currentMonth: String,
    val previousMonth: String,
    val currentAmountCents: Long,
    val previousAmountCents: Long,
    val deltaAmountCents: Long,
    val percentChange: Int?,
)

data class BudgetProgress(
    val month: String,
    val budgetCents: Long,
    val spentCents: Long,
    val remainingCents: Long,
    val progress: Float,
    val percent: Int,
    val overBudget: Boolean,
)

data class LifestyleStats(
    val month: String,
    val aiSubscriptionAmountCents: Long,
    val digitalAmountCents: Long,
    val maxExpense: Expense?,
    val recent7DaysAmountCents: Long,
    val frequentMerchants: List<FrequentMerchant>,
)

data class CategoryRule(
    val id: Long,
    val keyword: String,
    val category: String,
    val enabled: Boolean,
    val priority: Int,
    val amountMinCents: Long?,
    val amountMaxCents: Long?,
    val sourceContains: String?,
    val tagContains: String?,
    val createdAt: String,
    val updatedAt: String,
) {
    val hasConditions: Boolean =
        amountMinCents != null ||
            amountMaxCents != null ||
            !sourceContains.isNullOrBlank() ||
            !tagContains.isNullOrBlank()
}

data class MerchantAlias(
    val publicId: String,
    val canonicalMerchant: String,
    val canonicalKey: String,
    val alias: String,
    val aliasKey: String,
    val enabled: Boolean,
    val createdAt: String,
    val updatedAt: String,
)

data class RuleApplicationBatch(
    val publicId: String,
    val status: String,
    val pendingScanned: Int,
    val changedCount: Int,
    val createdAt: String,
    val rolledBackAt: String?,
) {
    val isRolledBack: Boolean = status == "rolled_back" || rolledBackAt != null
}

data class RuleApplicationRollback(
    val publicId: String,
    val status: String,
    val changed: Int,
    val skipped: Int,
    val rolledBackAt: String?,
)

data class RuleApplyPreviewItem(
    val id: Long,
    val merchant: String?,
    val currentCategory: String,
    val suggestedCategory: String,
    val ruleKeyword: String,
    val reason: String,
)

data class RuleApplyConfirmedResult(
    val dryRun: Boolean,
    val confirmedScanned: Int,
    val changedCount: Int,
    val items: List<RuleApplyPreviewItem>,
    val skippedNonDefaultCategory: Int,
    val noMatchCount: Int,
    val unchangedCount: Int,
    val conflictCount: Int,
    val scanLimitReached: Boolean,
    val scanLimit: Int,
    val previewToken: String?,
)

class ProtectedImage(
    val bytes: ByteArray,
    val contentType: String?,
)

data class ServerSettings(
    val accountName: String,
    val ledgerId: String?,
    val ledgerName: String,
    val ledgerIsDefault: Boolean?,
    val deviceName: String,
    val role: String,
    val status: String,
    val storageStatus: String,
    val pendingCount: Int,
    val confirmedCount: Int,
    val rejectedCount: Int,
    val suspectedDuplicateCount: Int,
    val uploadStorageBytes: Long,
    val latestUploadAt: String?,
)

class CsvExport(
    val fileName: String,
    val bytes: ByteArray,
)

enum class DiagnosticStatus {
    Pass,
    Warn,
    Fail,
}

data class DiagnosticCheck(
    val name: String,
    val status: DiagnosticStatus,
    val detail: String,
    val elapsedMs: Long,
)

data class ConnectionDiagnostics(
    val checks: List<DiagnosticCheck>,
) {
    val failedCount: Int = checks.count { it.status == DiagnosticStatus.Fail }
    val warningCount: Int = checks.count { it.status == DiagnosticStatus.Warn }
    val passedCount: Int = checks.count { it.status == DiagnosticStatus.Pass }
    val isHealthy: Boolean = failedCount == 0
}
