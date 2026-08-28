package com.ticketbox.viewmodel

import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseCorrectionOutcome
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.ExpenseRevisionPage
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.RepaymentDraft
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain

@OptIn(ExperimentalCoroutinesApi::class)
internal abstract class ExpenseFactViewModelTestBase {
    protected fun edit(block: suspend TestScope.(FakeExpenseFactActions) -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block(FakeExpenseFactActions())
        } finally {
            Dispatchers.resetMain()
        }
    }

    protected fun TestScope.viewModel(fake: FakeExpenseFactActions): ExpenseFactViewModel {
        val viewModel = ExpenseFactViewModel(expenseId = 7L, repository = fake)
        advanceUntilIdle()
        return viewModel
    }
}

/** Shared real-shape repository fake for the confirmed fact ViewModel tests. */
@Suppress("TooManyFunctions")
internal class FakeExpenseFactActions : ExpenseFactActions {
    var canModifyLedgerFlag: Boolean = true

    var baseExpense: Expense = Expense(
        id = 7L,
        publicId = "pub-7",
        amountCents = 1000L,
        homeCurrencyCode = "CNY",
        originalCurrency = CurrencyCode.CNY,
        originalCurrencyCode = CurrencyCode.CNY,
        originalAmountMinor = 1000L,
        merchant = "旧商家",
        category = "餐饮",
        note = null,
        source = "manual",
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "confirmed",
        expenseTime = null,
        createdAt = "2026-08-22T11:38:00Z",
        updatedAt = "2026-08-22T11:38:00Z",
        rowVersion = 1L,
        factRevision = 1L,
        confirmedAt = "2026-08-22T11:38:00Z",
        rejectedAt = null,
    )

    var itemsResult: Result<ExpenseItems> = Result.success(
        ExpenseItems(
            expenseId = 7L,
            parentAmountCents = 1000L,
            itemsTotalAmountCents = null,
            mismatchCents = null,
            items = emptyList(),
        ),
    )
    var correctResult: (Expense, ExpenseCorrectionDraft) -> Result<ExpenseCorrectionOutcome> =
        { expense, draft ->
            Result.success(
                ExpenseCorrectionOutcome.Synced(
                    expense = expense.copy(
                        originalCurrency = draft.originalCurrencyCode ?: expense.originalCurrency,
                        originalCurrencyCode = draft.originalCurrencyCode ?: expense.originalCurrencyCode,
                        originalCurrencyCodeRaw = draft.originalCurrencyCode?.storageKey
                            ?: expense.originalCurrencyCodeRaw,
                        originalAmountMinor = draft.originalAmountMinor ?: expense.originalAmountMinor,
                        merchant = draft.merchant ?: expense.merchant,
                        category = draft.category ?: expense.category,
                        tags = draft.tags ?: expense.tags,
                        note = draft.note ?: expense.note,
                        expenseTime = if (draft.expenseTimeChanged) {
                            draft.expenseTime
                        } else {
                            expense.expenseTime
                        },
                        valueScore = if (draft.valueScoreChanged) {
                            draft.valueScore
                        } else {
                            expense.valueScore
                        },
                        regretScore = if (draft.regretScoreChanged) {
                            draft.regretScore
                        } else {
                            expense.regretScore
                        },
                        rowVersion = expense.rowVersion + 1,
                        factRevision = expense.factRevision + 1,
                    ),
                    revision = ExpenseRevision(
                        publicId = "rev-2",
                        revisionNumber = 2L,
                        changeKind = "correction",
                        reason = draft.reason,
                        changedFields = listOfNotNull(
                            draft.merchant?.let { "merchant" },
                            draft.category?.let { "category" },
                            draft.items?.let { "items" },
                            draft.splits?.let { "splits" },
                        ),
                        before = null,
                        after = emptyMap(),
                        actorAccountName = "我",
                        actorDeviceName = "这台手机",
                        createdAt = "2026-08-28T20:12:00Z",
                    ),
                ),
            )
        }

    var correctCalls = 0
    var lastCorrectionDraft: ExpenseCorrectionDraft? = null
    var fetchExpenseCalls = 0
    var fetchRevisionsCalls = 0
    var fetchBillSplitSentCalls = 0

    override fun canModifyLedger(): Boolean = canModifyLedgerFlag

    override fun currentTimezoneId(): String = "Asia/Shanghai"

    override suspend fun fetchExpense(id: Long): Result<Expense> {
        fetchExpenseCalls++
        return Result.success(baseExpense)
    }

    override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> =
        Result.success(baseExpense)

    override suspend fun categories(): Result<List<String>> = Result.success(listOf("餐饮", "居家"))

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> =
        Result.failure(RepositoryException(errorCode = "image_not_found", message = "no image"))

    override suspend fun fetchImage(id: Long): Result<ProtectedImage> =
        Result.failure(RepositoryException(errorCode = "image_not_found", message = "no image"))

    override suspend fun fetchExpenseItems(id: Long): Result<ExpenseItems> = itemsResult

    override suspend fun fetchExpenseSplits(id: Long): Result<ExpenseSplits> = Result.success(
        ExpenseSplits(
            expenseId = 7L,
            parentAmountCents = 1000L,
            splitsTotalAmountCents = null,
            mismatchCents = null,
            splits = emptyList(),
        ),
    )

    override suspend fun fetchSplitMembers(): Result<List<FamilyMember>> = Result.success(emptyList())

    override suspend fun fetchExpenseRevisions(
        id: Long,
        page: Int,
        pageSize: Int,
    ): Result<ExpenseRevisionPage> {
        fetchRevisionsCalls++
        return Result.success(
            ExpenseRevisionPage(
                items = listOf(
                    ExpenseRevision(
                        publicId = "rev-1",
                        revisionNumber = 1L,
                        changeKind = "confirmed",
                        reason = "首次确认",
                        changedFields = emptyList(),
                        before = null,
                        after = emptyMap(),
                        actorAccountName = "我",
                        actorDeviceName = "这台手机",
                        createdAt = "2026-08-22T11:38:00Z",
                    ),
                ),
                page = 1,
                pageSize = 50,
                total = 1,
            ),
        )
    }

    override suspend fun correctExpenseAllowingOffline(
        expense: Expense,
        correction: ExpenseCorrectionDraft,
    ): Result<ExpenseCorrectionOutcome> {
        correctCalls++
        lastCorrectionDraft = correction
        return correctResult(expense, correction)
    }

    override suspend fun createRepaymentDraftFromExpense(expense: Expense): Result<RepaymentDraft> =
        Result.failure(RepositoryException(errorCode = "invalid_request", message = "not under test"))

    override suspend fun createBillSplitInvitation(
        expenseId: Long,
        receiverAccountId: Long,
        amountCents: Long,
    ): Result<BillSplitSent> =
        Result.failure(RepositoryException(errorCode = "invalid_request", message = "not under test"))

    override suspend fun fetchBillSplitSent(): Result<List<BillSplitSent>> {
        fetchBillSplitSentCalls++
        return Result.success(emptyList())
    }

    override suspend fun cancelBillSplitInvitation(publicId: String): Result<BillSplitSent> =
        Result.failure(RepositoryException(errorCode = "invalid_request", message = "not under test"))
}
