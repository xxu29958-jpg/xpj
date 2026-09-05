package com.ticketbox

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonReader
import com.squareup.moshi.JsonWriter
import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.addExpenseCorrectionWireAdapters
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.repository.ExpenseOffsetVoidOutboxPayload
import com.ticketbox.data.repository.DebtCreateOutboxPayload
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import com.ticketbox.data.remote.dto.addRecurringWireAdapters

internal class OutboxAdapterGraph {
    // ADR-0038 PR-2g.2 + 2g.3: outbox plumbing.
    //
    // A dedicated Moshi instance for the outbox dispatcher layer.
    // We don't share the one ApiClient builds internally because it
    // lives in private scope; using a separate instance is fine
    // since Moshi adapters are immutable and stateless. The outbox
    // payloads we serialise here MUST line up with the Retrofit DTOs
    // (same nullability + @Json names) since the dispatcher
    // deserialises a row back into the same DTO shape on replay.
    private val moshi: Moshi by lazy {
        Moshi.Builder()
            .addExpenseCorrectionWireAdapters()
            .addRecurringWireAdapters()
            .build()
    }

    // PR-2g.3: the SAME adapter is shared between the call-site
    // serialiser (ExpenseRepository routes IOException -> outbox.enqueue)
    // and the dispatcher (PatchExpenseDispatcher deserialises on
    // replay). Sharing guarantees toJson/fromJson roundtrip - if we
    // built two independent adapters they'd be byte-compatible
    // today but could drift if Moshi options change in one place.
    val patchExpenseAdapter: JsonAdapter<ExpenseUpdateRequest> = lazyJsonAdapter {
        moshi.adapter(ExpenseUpdateRequest::class.java)
    }

    val correctionAdapter: JsonAdapter<ExpenseCorrectionRequestDto> = lazyJsonAdapter {
        moshi.adapter(ExpenseCorrectionRequestDto::class.java)
    }

    // PR-2g.4: shared between UpdateCategoryRuleDispatcher
    // (deserialises on replay) and RuleRepository.updateCategoryRuleAllowingOffline
    // (serialises before enqueue). Same roundtrip guarantee as patchExpenseAdapter.
    val categoryRuleUpdateAdapter: JsonAdapter<CategoryRuleUpdateRequest> = lazyJsonAdapter {
        moshi.adapter(CategoryRuleUpdateRequest::class.java)
    }

    // PR-2g.5: DELETE adapters. Token-only payload shape; the dispatcher rebuilds
    // the token from row.expectedRowVersion on replay (single source of truth -
    // round-8 P3#5).
    val categoryRuleDeleteAdapter: JsonAdapter<CategoryRuleDeleteRequest> = lazyJsonAdapter {
        moshi.adapter(CategoryRuleDeleteRequest::class.java)
    }
    val merchantAliasDeleteAdapter: JsonAdapter<MerchantAliasDeleteRequest> = lazyJsonAdapter {
        moshi.adapter(MerchantAliasDeleteRequest::class.java)
    }

    // PR-2g.6: PATCH merchant alias adapter. Shared between
    // UpdateMerchantAliasDispatcher and MerchantRepository.updateMerchantAliasAllowingOffline.
    val merchantAliasUpdateAdapter: JsonAdapter<MerchantAliasUpdateRequest> = lazyJsonAdapter {
        moshi.adapter(MerchantAliasUpdateRequest::class.java)
    }

    // PR-2g.7: token-only adapter shared between the confirm / reject dispatchers
    // and ExpensePendingRepository's offline call sites. POST /api/expenses/{id}/confirm
    // and .../reject take the same ExpenseStateTokenRequest body, so one adapter serves both.
    val expenseStateTokenAdapter: JsonAdapter<ExpenseStateTokenRequest> = lazyJsonAdapter {
        moshi.adapter(ExpenseStateTokenRequest::class.java)
    }

    // PR-D: body-carrying adapter shared between ReplaceItemsDispatcher and
    // ExpenseDetailRepository's offline items-editor call site (PUT
    // /api/expenses/{id}/items). Same roundtrip guarantee as patchExpenseAdapter.
    val replaceItemsAdapter: JsonAdapter<ExpenseItemReplaceRequestDto> = lazyJsonAdapter {
        moshi.adapter(ExpenseItemReplaceRequestDto::class.java)
    }

    // ADR-0042 Slice E-1: body-carrying adapter shared between
    // ReplaceSplitsDispatcher and ExpenseDetailRepository's offline splits-editor call
    // site (PUT /api/expenses/{id}/splits). Same roundtrip guarantee as replaceItemsAdapter.
    val replaceSplitsAdapter: JsonAdapter<ExpenseSplitReplaceRequestDto> = lazyJsonAdapter {
        moshi.adapter(ExpenseSplitReplaceRequestDto::class.java)
    }

    // ADR-0042 Slice E-2: body-carrying adapter shared between
    // RecognizeTextDispatcher and ExpenseDetailRepository's offline "粘贴文字识别" call
    // site (POST /api/expenses/{id}/recognize-text). Same roundtrip guarantee as
    // replaceItemsAdapter.
    val recognizeTextAdapter: JsonAdapter<ExpenseRecognizeTextRequestDto> = lazyJsonAdapter {
        moshi.adapter(ExpenseRecognizeTextRequestDto::class.java)
    }

    // issue #65 slice 4: body adapter shared between the offline-aware manual
    // create (ExpenseLedgerRepositoryActions / ExpenseRepositoryCore.enqueueLocalCreate)
    // and CreateExpenseDispatcher's replay. Same roundtrip guarantee as patchExpenseAdapter.
    val manualCreateAdapter: JsonAdapter<ExpenseManualCreateRequestDto> = lazyJsonAdapter {
        moshi.adapter(ExpenseManualCreateRequestDto::class.java)
    }

    val offsetCreateAdapter: JsonAdapter<ExpenseOffsetCreateRequestDto> = lazyJsonAdapter {
        moshi.adapter(ExpenseOffsetCreateRequestDto::class.java)
    }

    val offsetVoidAdapter: JsonAdapter<ExpenseOffsetVoidOutboxPayload> = lazyJsonAdapter {
        moshi.adapter(ExpenseOffsetVoidOutboxPayload::class.java)
    }

    // ADR-0042 Slice F: PATCH /api/goals/{publicId} adapter. Shared between
    // UpdateGoalDispatcher and ReportsRepository.updateGoalAllowingOffline.
    val goalUpdateAdapter: JsonAdapter<GoalUpdateRequestDto> = lazyJsonAdapter {
        moshi.adapter(GoalUpdateRequestDto::class.java)
    }

    // ADR-0042 Slice F: PATCH /api/income-plans/{publicId} adapter. Shared
    // between UpdateIncomePlanDispatcher and IncomePlanRepository.updateAllowingOffline.
    val incomePlanUpdateAdapter: JsonAdapter<IncomePlanUpdateRequestDto> = lazyJsonAdapter {
        moshi.adapter(IncomePlanUpdateRequestDto::class.java)
    }

    val recurringCreateAdapter: JsonAdapter<RecurringItemCreateRequestDto> = lazyJsonAdapter {
        moshi.adapter(RecurringItemCreateRequestDto::class.java)
    }

    val recurringUpdateAdapter: JsonAdapter<RecurringItemUpdateRequestDto> = lazyJsonAdapter {
        moshi.adapter(RecurringItemUpdateRequestDto::class.java)
    }

    val debtCreateAdapter: JsonAdapter<DebtCreateOutboxPayload> = lazyJsonAdapter {
        moshi.adapter(DebtCreateOutboxPayload::class.java)
    }
}

private fun <T> lazyJsonAdapter(factory: () -> JsonAdapter<T>): JsonAdapter<T> =
    object : JsonAdapter<T>() {
        private val delegate: JsonAdapter<T> by lazy(factory)

        override fun fromJson(reader: JsonReader): T? = delegate.fromJson(reader)

        override fun toJson(writer: JsonWriter, value: T?) {
            delegate.toJson(writer, value)
        }

        override fun toString(): String = "LazyJsonAdapter"
    }
