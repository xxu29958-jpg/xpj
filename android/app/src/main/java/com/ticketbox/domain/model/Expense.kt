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

data class CategoryStats(
    val category: String,
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
)

data class FrequentMerchant(
    val merchant: String,
    val count: Int,
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
    val createdAt: String,
    val updatedAt: String,
)

class ProtectedImage(
    val bytes: ByteArray,
    val contentType: String?,
)

data class ServerSettings(
    val maxUploadSizeMb: Int,
    val generateThumbnail: Boolean,
    val deleteImageAfterConfirm: Boolean,
    val deleteImageAfterDays: Int,
    val ocrProvider: String,
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
