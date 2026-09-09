package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.SessionCredentialProvider

/**
 * Server/session plumbing shared by repositories that issue guarded API calls.
 */
data class ServerSessionBinding(
    val apiClient: ApiServiceFactory,
    val settingsStore: TicketboxSettingsStore,
    val sessionStore: LocalSessionStore,
    val credentials: SessionCredentialProvider,
    val apiProvider: ApiServiceProvider,
)

/**
 * Correction publication requires its durable owner and both supported/display-only codecs.
 * Other mutation adapters retain their existing independently scoped behavior.
 */
data class ExpenseOfflineMutationWiring(
    val outbox: OutboxRepository,
    val correctionAdapter: JsonAdapter<ExpenseCorrectionPayload>,
    val legacyCorrectionAdapter: JsonAdapter<ExpenseCorrectionRequestDto>,
    val billSplitCreateAdapter: JsonAdapter<BillSplitCreatePayload>,
    val billSplitReceiptAdapter: JsonAdapter<com.ticketbox.data.remote.dto.BillSplitSentDto>,
    val patchExpenseAdapter: JsonAdapter<ExpenseUpdateRequest>? = null,
    val expenseStateTokenAdapter: JsonAdapter<ExpenseStateTokenRequest>? = null,
    val replaceItemsAdapter: JsonAdapter<ExpenseItemReplaceRequestDto>? = null,
    val replaceSplitsAdapter: JsonAdapter<ExpenseSplitReplaceRequestDto>? = null,
    val recognizeTextAdapter: JsonAdapter<ExpenseRecognizeTextRequestDto>? = null,
    val manualCreateAdapter: JsonAdapter<ExpenseManualCreateRequestDto>,
    val offsetCreateAdapter: JsonAdapter<ExpenseOffsetCreateRequestDto>? = null,
    val offsetVoidAdapter: JsonAdapter<ExpenseOffsetVoidOutboxPayload>? = null,
)

/**
 * Offline replay wiring for category-rule update/delete mutations.
 */
data class CategoryRuleOfflineMutationWiring(
    val outbox: OutboxRepository? = null,
    val updateAdapter: JsonAdapter<CategoryRuleUpdateRequest>? = null,
    val deleteAdapter: JsonAdapter<CategoryRuleDeleteRequest>? = null,
    val submissionAdapter: JsonAdapter<CategoryRuleSubmissionPayload>? = null,
    val receiptAdapter: JsonAdapter<com.ticketbox.data.remote.dto.CategoryRuleDto>? = null,
)

/**
 * Offline replay wiring for merchant-alias update/delete mutations.
 */
data class MerchantAliasOfflineMutationWiring(
    val outbox: OutboxRepository? = null,
    val deleteAdapter: JsonAdapter<MerchantAliasDeleteRequest>? = null,
    val updateAdapter: JsonAdapter<MerchantAliasUpdateRequest>? = null,
)
