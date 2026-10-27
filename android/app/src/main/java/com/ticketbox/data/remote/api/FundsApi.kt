package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.AccountPostingDto
import com.ticketbox.data.remote.dto.CreditPaymentDto
import com.ticketbox.data.remote.dto.CreditPaymentVoidDto
import com.ticketbox.data.remote.dto.ExpenseFundingCommandDto
import com.ticketbox.data.remote.dto.FinancialAccountCreateDto
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.remote.dto.FinancialAccountEditDto
import com.ticketbox.data.remote.dto.FinancialAccountReceiptDto
import com.ticketbox.data.remote.dto.InstallmentCommandDto
import com.ticketbox.domain.model.ExpenseFundingView
import com.ticketbox.domain.model.FundsOverview
import com.ticketbox.domain.model.Installments
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path

interface FundsApi : FundsReadApi, FundsWriteApi

interface FundsReadApi {
    @GET("api/budget/envelopes/history/list")
    suspend fun envelopeHistory(@retrofit2.http.Query("before_version") beforeVersion: Long?): List<com.ticketbox.domain.model.EnvelopeRevision>
    @GET("api/budget/envelopes/{month}")
    suspend fun envelopes(@Path("month") month: String): com.ticketbox.domain.model.Envelopes
    @GET("api/funds/accounts/existing-debts/list")
    suspend fun existingFundDebts(): List<com.ticketbox.domain.model.ExistingDebtChoice>
    @GET("api/funds/accounts/templates/list")
    suspend fun fundsAccountChoices(): List<com.ticketbox.domain.model.AccountChoice>
    @GET("api/funds/accounts/{id}/installments")
    suspend fun installments(@Path("id") id: String): Installments
    @GET("api/expenses/{id}/funding")
    suspend fun expenseFunding(@Path("id") id: Long): ExpenseFundingView
    @GET("api/funds/accounts/summary/net-worth")
    suspend fun fundsOverview(): FundsOverview
    @GET("api/funds/accounts")
    suspend fun fundsAccounts(): List<FinancialAccountDto>
    @GET("api/funds/accounts/{id}")
    suspend fun fundsAccount(@Path("id") id: String): FinancialAccountDto
}

interface FundsWriteApi : FundsCorrectionApi {
    @POST("api/funds/accounts/{id}/credit-applications")
    suspend fun applyRetainedCredit(@Path("id") id: String, @Body body: com.ticketbox.data.remote.dto.CreditApplicationCreateDto,
        @Header("Idempotency-Key") key: String): FinancialAccountReceiptDto
    @POST("api/funds/accounts/{id}/fees")
    suspend fun incurCreditFee(@Path("id") id: String, @Body body: com.ticketbox.data.remote.dto.CreditFeeCreateDto,
        @Header("Idempotency-Key") key: String): FinancialAccountReceiptDto
    @PUT("api/budget/envelopes/{month}")
    suspend fun saveEnvelopes(@Path("month") month: String,
        @Body body: com.ticketbox.data.remote.dto.EnvelopeSaveDto,
        @Header("Idempotency-Key") key: String): com.ticketbox.data.remote.dto.EnvelopeReceiptDto
    @POST("api/funds/accounts/{id}/installments")
    suspend fun saveInstallments(@Path("id") id: String, @Body body: InstallmentCommandDto,
        @Header("Idempotency-Key") key: String): FinancialAccountReceiptDto
    @POST("api/expenses/{id}/funding")
    suspend fun saveExpenseFunding(@Path("id") id: Long, @Body body: ExpenseFundingCommandDto,
        @Header("Idempotency-Key") key: String): ExpenseFundingView
    @POST("api/funds/accounts")
    suspend fun createFundsAccount(@Body body: FinancialAccountCreateDto, @Header("Idempotency-Key") key: String): FinancialAccountReceiptDto
    @PATCH("api/funds/accounts/{id}")
    suspend fun editFundsAccount(@Path("id") id: String, @Body body: FinancialAccountEditDto,
        @Header("Idempotency-Key") key: String): FinancialAccountReceiptDto
    @POST("api/funds/accounts/{id}/repay")
    suspend fun payCreditAccount(@Path("id") id: String, @Body body: CreditPaymentDto,
        @Header("Idempotency-Key") key: String): FinancialAccountReceiptDto
    @POST("api/funds/accounts/{id}/activities")
    suspend fun postFundsActivity(@Path("id") id: String, @Body body: AccountPostingDto,
        @Header("Idempotency-Key") key: String): FinancialAccountReceiptDto
}

/** Corrections share the original fact owners and stable command receipts. */
interface FundsCorrectionApi {
    @POST("api/funds/accounts/{id}/activities/void")
    suspend fun voidFundsActivity(@Path("id") id: String, @Body body: com.ticketbox.data.remote.dto.AccountActivityVoidDto,
        @Header("Idempotency-Key") key: String): FinancialAccountReceiptDto
    @POST("api/funds/accounts/{id}/credit-applications/void")
    suspend fun voidCreditApplication(@Path("id") id: String, @Body body: com.ticketbox.data.remote.dto.CreditApplicationVoidDto,
        @Header("Idempotency-Key") key: String): FinancialAccountReceiptDto
    @POST("api/funds/accounts/{id}/repayments/void")
    suspend fun voidCreditPayment(@Path("id") id: String, @Body body: CreditPaymentVoidDto,
        @Header("Idempotency-Key") key: String): FinancialAccountReceiptDto
}
