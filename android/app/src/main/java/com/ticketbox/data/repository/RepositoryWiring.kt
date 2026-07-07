package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.security.SessionTokenStore

/**
 * Server/session plumbing shared by repositories that issue guarded API calls.
 */
data class ServerSessionBinding(
    val apiClient: ApiServiceFactory,
    val settingsStore: TicketboxSettingsStore,
    val tokenStore: SessionTokenStore,
    val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
)

/**
 * Offline replay wiring for expense mutations. Tests and feature surfaces wire
 * only the mutation adapters they exercise; a missing adapter keeps that path
 * on the direct-call failure behavior.
 */
data class ExpenseOfflineMutationWiring(
    val outbox: OutboxRepository? = null,
    val patchExpenseAdapter: JsonAdapter<ExpenseUpdateRequest>? = null,
    val expenseStateTokenAdapter: JsonAdapter<ExpenseStateTokenRequest>? = null,
    val replaceItemsAdapter: JsonAdapter<ExpenseItemReplaceRequestDto>? = null,
    val replaceSplitsAdapter: JsonAdapter<ExpenseSplitReplaceRequestDto>? = null,
    val recognizeTextAdapter: JsonAdapter<ExpenseRecognizeTextRequestDto>? = null,
    val manualCreateAdapter: JsonAdapter<ExpenseManualCreateRequestDto>? = null,
)

/**
 * Offline replay wiring for category-rule update/delete mutations.
 */
data class CategoryRuleOfflineMutationWiring(
    val outbox: OutboxRepository? = null,
    val updateAdapter: JsonAdapter<CategoryRuleUpdateRequest>? = null,
    val deleteAdapter: JsonAdapter<CategoryRuleDeleteRequest>? = null,
)

/**
 * Offline replay wiring for merchant-alias update/delete mutations.
 */
data class MerchantAliasOfflineMutationWiring(
    val outbox: OutboxRepository? = null,
    val deleteAdapter: JsonAdapter<MerchantAliasDeleteRequest>? = null,
    val updateAdapter: JsonAdapter<MerchantAliasUpdateRequest>? = null,
)
