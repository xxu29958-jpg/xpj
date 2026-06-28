package com.ticketbox.domain.model

data class Expense(
    // issue #65 slice 4: the server id when synced; for a not-yet-synced offline
    // manual create it is a NEGATIVE stand-in derived from the local Room PK
    // (``serverId ?: -localPk`` in ExpenseEntity.toDomain). Negative ids are
    // unique per local row and disjoint from positive server ids, so the
    // existing id-keyed UI machinery (list keys, selection, action-gating) keeps
    // working without collision. Never send a non-positive id to the server —
    // address such rows via [clientRef] / ``expense:local:{clientRef}`` instead.
    val id: Long,
    val publicId: String,
    val amountCents: Long?,
    val homeAmountCents: Long? = amountCents,
    val homeCurrency: CurrencyCode = FxContract.HomeCurrency,
    val originalCurrency: CurrencyCode = FxContract.HomeCurrency,
    val originalAmount: String? = null,
    val fxRate: String? = null,
    val fxRateDate: String? = null,
    val fxSource: String? = null,
    val fxStatus: String = FxContract.StatusReady,
    val originalCurrencyCode: CurrencyCode = FxContract.HomeCurrency,
    val originalAmountMinor: Long? = null,
    val exchangeRateToCny: String? = null,
    val exchangeRateDate: String? = null,
    val exchangeRateSource: String? = null,
    val merchant: String?,
    val category: String,
    val note: String?,
    val source: String,
    val imagePath: String?,
    val thumbnailPath: String?,
    val imageDeletedAt: String? = null,
    val thumbnailDeletedAt: String? = null,
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
    val rowVersion: Long,
    val confirmedAt: String?,
    val rejectedAt: String?,
    // issue #65 slice 4: present iff this row was created on this device and
    // carries a device-unique client ref. Stays set after sync (the audit link);
    // use [pendingSync] — not its nullness — to ask "is this synced yet".
    val clientRef: String? = null,
    // issue #65 slice 4: true while an offline manual create has no server id yet
    // (its CreateExpense outbox row hasn't drained). Derived from
    // ``serverId == null`` in ExpenseEntity.toDomain. A synced row is false.
    val pendingSync: Boolean = false,
)

/**
 * UI/UX 第三波 批 13：本票是否可发起跨账本拆账邀请（ADR-0029）。
 * 已确认 + 有金额 + 非「收到的拆账」（不能对收到的拆账再拆，后端 split_chain_not_allowed
 * 亦兜底）+ 可写。卡片可见性与 VM 懒加载触发共用这一个判断，避免两处漂移。
 */
fun Expense.canInitiateBillSplit(readOnly: Boolean): Boolean =
    status == "confirmed" &&
        // issue #65 slice 5: a not-yet-synced offline create has no server id, so
        // a cross-ledger split invitation (which addresses the sender expense by
        // server id) can't be issued until it syncs.
        !pendingSync &&
        amountCents != null &&
        source != ExpenseSourceValues.BILL_SPLIT_RECEIVED &&
        !readOnly

/**
 * [Expense.source] 的服务端存储值（domain 值，非 UI 文案）。中文 token 是后端
 * 落库的历史值，镜像 `web_stats_service.SOURCE_LABELS` 的键；展示层据此映射到
 * string 资源，未列出的值原样回显。
 */
object ExpenseSourceValues {
    const val IPHONE_SCREENSHOT = "iPhone截图"
    const val ANDROID_SCREENSHOT = "Android截图"
    const val MANUAL_ENTRY = "手动记账"
    const val CSV_IMPORT = "CSV导入"
    const val BILL_SPLIT_RECEIVED = "bill_split_received"

    /** 通知草稿来源前缀（完整值 = 前缀 + 渠道名），镜像后端同名前缀。 */
    const val NOTIFICATION_DRAFT_PREFIX = "通知草稿:"
}

data class ExpenseDraft(
    val amountCents: Long?,
    val originalCurrencyCode: CurrencyCode? = null,
    val originalAmountMinor: Long? = null,
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
    val kind: String = ExpenseItemKind.PRODUCT,
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
    val itemsSumStatus: String = ItemsSumStatus.NO_ITEMS,
    val items: List<ExpenseItem>,
) {
    val hasMismatch: Boolean
        get() = mismatchCents != null && mismatchCents != 0L
    val mismatchKnown: Boolean
        get() = itemsSumStatus == ItemsSumStatus.MISMATCH_KNOWN
    val mismatchAcknowledged: Boolean
        get() = itemsSumStatus == ItemsSumStatus.MISMATCH_ACKNOWLEDGED
}

object ExpenseItemKind {
    const val PRODUCT = "product"
    const val DISCOUNT = "discount"
    const val TAX = "tax"
    const val SERVICE_FEE = "service_fee"
}

object ItemsSumStatus {
    const val MATCHED = "matched"
    const val MISMATCH_KNOWN = "mismatch_known"
    const val MISMATCH_ACKNOWLEDGED = "mismatch_acknowledged"
    const val NO_ITEMS = "no_items"
}

data class ExpenseItemDraft(
    val name: String,
    val quantityText: String?,
    val unitPriceCents: Long?,
    val amountCents: Long?,
    val category: String?,
    val rawText: String?,
    val confidence: Double?,
    val kind: String = ExpenseItemKind.PRODUCT,
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

/**
 * A merchant the user spent at recently, paired with the category last used for
 * it. Drives the ledger "最近" quick-fill chips on the manual-entry sheet — one
 * tap fills the merchant and carries the matching category. Derived purely from
 * the confirmed cache (see [recentLedgerMerchants]); never an OCR/AI guess.
 */
data class RecentMerchant(
    val merchant: String,
    val category: String,
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
    val bestValueExpenses: List<Expense> = emptyList(),
    val mostRegrettedExpenses: List<Expense> = emptyList(),
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
    val rowVersion: Long,
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
    val rowVersion: Long,
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
