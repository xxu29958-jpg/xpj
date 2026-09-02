package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.data.remote.dto.DebtBillParseResponseDto
import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtForgiveCreateRequestDto
import com.ticketbox.data.remote.dto.DebtKindSetRequestDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.DebtVoidCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import okhttp3.MultipartBody
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.Multipart
import retrofit2.http.Part
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface DebtApi {
    // Default reads the full ledger. The optional task lens is resolved by the server for
    // the authenticated account, never by filtering owner-relative direction on the client.
    @GET("api/debts")
    suspend fun debts(@Query("lens") lens: String? = null): DebtListResponseDto

    // Personal receivables in the active ledger plus cross-ledger member receivables.
    // Only cross-ledger rows have a redacted ledger_id; external rows are included too.
    @GET("api/debts/receivables")
    suspend fun debtReceivables(): DebtListResponseDto

    @POST("api/debts")
    suspend fun createDebt(
        @Body request: DebtCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    // ADR-0049 §D: transient debt-bill OCR/vision parser. Multipart image in, suggestion fields
    // out; no Debt is created until the user confirms the normal create form.
    @Multipart
    @POST("api/debts/parse-bill")
    suspend fun parseDebtBill(@Part file: MultipartBody.Part): DebtBillParseResponseDto

    // ADR-0049 §2 (slice 8c): one Debt's server-derived fold (for the detail screen). 404
    // debt_not_found; a cross-ledger participant gets the redacted shell (ledger_id null, §5.2).
    @GET("api/debts/{publicId}")
    suspend fun debt(@Path("publicId") publicId: String): DebtDto

    // ADR-0049 §3 (slice 8c) direct fact writes for external/manual Debt (member/bill_split go
    // through the slice-3 proposal flow, §5.2 → 409 here). Each carries expected_row_version in the
    // body (§2.1 stale-intent fence + §3.6 fingerprint) and an ADR-0042 intent-time idempotency key
    // in the header (nullable for Retrofit ergonomics — the repository always supplies a UUID). The
    // repayment route returns RepaymentCreateResponse (a DebtResponse superset); Moshi keeps the
    // shared fold fields and drops the unused repayment_public_id, so DebtDto is the right shape.
    @POST("api/debts/{publicId}/repayments")
    suspend fun recordDebtRepayment(
        @Path("publicId") publicId: String,
        @Body request: RepaymentCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    @POST("api/debts/{publicId}/adjustments")
    suspend fun recordDebtAdjustment(
        @Path("publicId") publicId: String,
        @Body request: DebtAdjustmentCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    @POST("api/debts/{publicId}/void")
    suspend fun voidDebt(
        @Path("publicId") publicId: String,
        @Body request: DebtVoidCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    // ADR-0049 §7.0 / 8e-6e: set or correct an existing external Debt's repayment-rhythm
    // classification (debt_kind). OCC token in the body (bumps row_version; NOT fold-changing —
    // it gates only the payoff projection, not remaining/paid/status) + an ADR-0042 intent-time
    // idempotency key in the header (nullable for Retrofit ergonomics — the repository always
    // supplies a UUID). Returns the re-serialized fold (DebtResponse → DebtDto) so the detail
    // screen swaps in the fresh row_version + debt_kind.
    @POST("api/debts/{publicId}/kind")
    suspend fun setDebtKind(
        @Path("publicId") publicId: String,
        @Body request: DebtKindSetRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    // ADR-0049 §3.7 / §4 (slice 8e-3): the creditor forgives a member Debt's remaining
    // ("算了，不用还了"). One-sided (no debtor confirmation), member + creditor only (the server
    // 403s a debtor / 409s an external Debt). Fold-changing → it carries expected_row_version in the
    // body + an ADR-0042 intent-time idempotency key in the header, and replies with the fold-after
    // DebtResponse (DebtDto: cleared + is_forgiven). §5.2: a cross-ledger creditor gets the shell.
    @POST("api/debts/{publicId}/forgive")
    suspend fun forgiveDebt(
        @Path("publicId") publicId: String,
        @Body request: DebtForgiveCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto
}
