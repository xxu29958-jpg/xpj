package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import java.io.File
import kotlin.reflect.KClass
import kotlin.reflect.full.primaryConstructor
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * ADR-0043 review follow-up — generative round-trip contract gate.
 *
 * The hand-written `*DtoContractTest` fixtures encode "the shape a developer THOUGHT
 * the server sends" — which is exactly how the flat-vs-nested `ErrorDto` drift could
 * survive until a human review caught it ([[feedback_occ_test_token_from_rendered_carrier]]).
 * This gate instead drives each DTO from the backend's committed OpenAPI snapshot
 * (`docs/architecture/openapi_contract.json`):
 *
 *  1. **Name parity** — every `@Json` wire name on the DTO must be a property of its
 *     backend schema. A backend rename/drop leaves an orphan field here → CI red.
 *     The live hazard is `ExpenseDto`'s FX surface (`fx_rate` / `exchange_rate_*` /
 *     `original_amount*`): all nullable-with-default, so today a backend rename just
 *     degrades to a silent `null` and no hand-written test reddens.
 *  2. **Generative round-trip** — synthesize a typed instance FROM the schema and
 *     decode it through the REAL production Moshi (`KotlinJsonAdapterFactory`, the
 *     same builder `ApiClient` uses). A backend type change → Moshi decode throws.
 *
 * The mapping is explicit because Android `XxxDto` ↔ backend `XxxResponse` is NOT 1:1
 * by name (no shared registry). Grow [pairs] as more DTOs are brought under the gate.
 */
class OpenApiContractGateTest {

    private data class Pairing(val dto: KClass<*>, val schema: String)

    private val pairs = listOf(
        Pairing(ErrorDto::class, "ErrorResponse"),
        Pairing(ExpenseDto::class, "ExpenseResponse"),
        // Dedicated manual-create DTO (no OCC-token field) + the PATCH body it
        // was split from — the forward check is the forbid-protection: a DTO
        // field the backend model doesn't declare would 422 at runtime.
        Pairing(ExpenseManualCreateRequestDto::class, "ExpenseManualCreateRequest"),
        Pairing(ExpenseUpdateRequest::class, "ExpenseUpdateRequest"),
        Pairing(IncomePlanDto::class, "IncomePlanResponse"),
        Pairing(IncomePlanListResponseDto::class, "IncomePlanListResponse"),
        Pairing(IncomePlanCreateRequestDto::class, "IncomePlanCreateRequest"),
        Pairing(IncomePlanUpdateRequestDto::class, "IncomePlanUpdateRequest"),
        Pairing(IncomePlanTokenRequestDto::class, "IncomePlanTokenRequest"),
        Pairing(BillSplitInviteRequestDto::class, "BillSplitInviteRequest"),
        Pairing(BillSplitAcceptRequestDto::class, "BillSplitAcceptRequest"),
        Pairing(BillSplitSentDto::class, "BillSplitSentResponse"),
        Pairing(BillSplitInboxDto::class, "BillSplitInboxResponse"),
        Pairing(BillSplitSentListResponseDto::class, "BillSplitSentListResponse"),
        Pairing(BillSplitInboxListResponseDto::class, "BillSplitInboxListResponse"),
        Pairing(DiscretionaryResponseDto::class, "DiscretionaryResponse"),
        Pairing(BudgetAdviseRequestDto::class, "BudgetAdviseRequest"),
        Pairing(BudgetSuggestionDto::class, "BudgetSuggestionDto"),
        Pairing(BudgetAdviceDto::class, "BudgetAdviceDto"),
        Pairing(BudgetAdviseResponseDto::class, "BudgetAdviseResponse"),
        Pairing(RecurringCandidateItemDto::class, "RecurringCandidateItem"),
        Pairing(RecurringCandidatesResponseDto::class, "RecurringCandidatesResponse"),
        Pairing(DataQualitySummaryDto::class, "DataQualitySummaryResponse"),
        Pairing(TagListItemDto::class, "TagListItem"),
        Pairing(TagManagementListDto::class, "TagManagementListResponse"),
        Pairing(TagDetailDto::class, "TagDetailResponse"),
        Pairing(TagMutationDto::class, "TagMutationResponse"),
        Pairing(TagUndoDto::class, "TagUndoResponse"),
        // 批 13 拆账发起:成员 API 增 account_id(receiver_account_id 的来源);
        // snapshot regen 后入闸,防该字段被后端静默漂移。
        Pairing(LedgerMemberDto::class, "LedgerMemberResponse"),
        // 轴6 备份超龄:status/private 的窄投影(HealthResponse 全字段可空,
        // required 为空,反向检查零压力;正向防备份三字段被后端改名漂移)。
        Pairing(StatusPrivateDto::class, "HealthResponse"),
        // 轴7 发邀请:create 请求是 extra=forbid(多字段=422),正向检查即 forbid 防线;
        // 响应含一次性明文 invite_token,字段漂移=邀请链路静默断。
        Pairing(InvitationCreateRequestDto::class, "InvitationCreateRequest"),
        Pairing(InvitationSummaryDto::class, "InvitationSummaryResponse"),
        Pairing(InvitationCreateResponseDto::class, "InvitationCreateResponse"),
        // issue #65 slice 6b owner "My Devices" surface. Rename body reuses the
        // backend AdminDeviceRenameRequest; the pairing-code response carries the
        // one-time plaintext code — a field drift = the add-device link silently
        // breaks. The two request bodies are additionalProperties=false (forward
        // check = the forbid protection).
        Pairing(MyDeviceDto::class, "MyDeviceResponse"),
        Pairing(MyDeviceListResponseDto::class, "MyDeviceListResponse"),
        Pairing(DeviceRenameRequestDto::class, "AdminDeviceRenameRequest"),
        Pairing(PairingCodeCreateRequestDto::class, "PairingCodeCreateRequest"),
        Pairing(PairingCodeResponseDto::class, "PairingCodeResponse"),
        // ADR-0051 current-ledger recycle bin. Restore body is
        // additionalProperties=false (forward check = forbid protection);
        // response message is server-authored copy surfaced by the VM.
        Pairing(RecycleBinItemDto::class, "RecycleBinItemResponse"),
        Pairing(RecycleBinListResponseDto::class, "RecycleBinListResponse"),
        Pairing(RecycleBinRestoreRequestDto::class, "RecycleBinRestoreRequest"),
        Pairing(RecycleBinRestoreResponseDto::class, "RecycleBinRestoreResponse"),
        // ADR-0053 merchant catalog Android management surface. Request bodies
        // are additionalProperties=false; response fields include the row
        // version used by hide/delete OCC.
        Pairing(MerchantCatalogDto::class, "MerchantCatalogResponse"),
        Pairing(MerchantCatalogListDto::class, "MerchantCatalogListResponse"),
        Pairing(MerchantCatalogCreateRequest::class, "MerchantCatalogCreateRequest"),
        Pairing(MerchantCatalogUpdateRequest::class, "MerchantCatalogUpdateRequest"),
        Pairing(MerchantCatalogDeleteRequest::class, "MerchantCatalogDeleteRequest"),
        Pairing(MerchantCatalogMergeRequest::class, "MerchantCatalogMergeRequest"),
        Pairing(MerchantCatalogMergeDto::class, "MerchantCatalogMergeResponse"),
        // ADR-0049 §6 (slice 7) debt_repayment goal surface. GoalDto was previously
        // ungated — slice 6 widened GoalResponse (the spend fields became nullable +
        // a nested debt_repayment block) so bring it under the gate now, along with
        // the nested evaluation/link DTOs and the two debt-link request bodies
        // (additionalProperties=false → the forward check is the forbid protection).
        Pairing(GoalDto::class, "GoalResponse"),
        Pairing(GoalListResponseDto::class, "GoalListResponse"),
        // ADR-0049 §6 (slice 8b) create body — one DTO for both goal types. The schema is
        // additionalProperties=false (forward check = forbid protection: a debt-shape field
        // the backend doesn't declare would 422), and the debt fields (goal_type /
        // debt_public_ids) must exist in the schema for the debt-goal create to deserialize.
        Pairing(GoalCreateRequestDto::class, "GoalCreateRequest"),
        Pairing(DebtRepaymentEvaluationDto::class, "DebtRepaymentEvaluation"),
        Pairing(DebtGoalLinkViewDto::class, "DebtGoalLinkView"),
        Pairing(DebtGoalLinksReplaceRequestDto::class, "DebtGoalLinksReplaceRequest"),
        Pairing(DebtGoalIntegrityReviewRequestDto::class, "DebtGoalIntegrityReviewRequest"),
        // ADR-0049 §7.0 (slice 8e-6c) payoff-deadline setter body. additionalProperties=false →
        // the forward check is the forbid protection; target_date is optional on the wire (a
        // setter: omitted == clear), so the reverse check only requires expected_row_version.
        Pairing(DebtGoalTargetDateRequestDto::class, "DebtGoalTargetDateRequest"),
        // ADR-0049 §2 (slice 8) Debt entity surface. DebtDto models all 22 DebtResponse
        // properties (reverse check needs every required field; +is_forgiven in slice 8e-3); the
        // create body is additionalProperties=false → the forward check is the forbid protection.
        Pairing(DebtDto::class, "DebtResponse"),
        Pairing(DebtListResponseDto::class, "DebtListResponse"),
        Pairing(DebtCreateRequestDto::class, "DebtCreateRequest"),
        // ADR-0049 §3 (slice 8c) direct fact-write bodies. Each is additionalProperties=false →
        // the forward check is the forbid protection; the home-currency-only DTOs intentionally omit
        // the optional foreign-currency fields (a subset of the schema, so the forward check passes).
        Pairing(RepaymentCreateRequestDto::class, "RepaymentCreateRequest"),
        Pairing(DebtAdjustmentCreateRequestDto::class, "DebtAdjustmentCreateRequest"),
        Pairing(DebtVoidCreateRequestDto::class, "DebtVoidCreateRequest"),
        // ADR-0049 §3.7 / §4 (slice 8e-3) creditor-forgive body (expected_row_version only),
        // additionalProperties=false → forward check is the forbid protection.
        Pairing(DebtForgiveCreateRequestDto::class, "DebtForgiveCreateRequest"),
        // ADR-0049 §7.0 / 8e-6e debt_kind correction setter body. additionalProperties=false → the
        // forward check is the forbid protection; both fields (debt_kind / expected_row_version) are
        // backend-`required`, so the reverse check needs them modeled (they are). DebtDto +
        // DebtCreateRequestDto adopting debt_kind is silent here (DebtResponse/DebtCreateRequest both
        // default it → not `required`, no reverse pressure; it IS a declared property → forward OK).
        Pairing(DebtKindSetRequestDto::class, "DebtKindSetRequest"),
        // ADR-0049 §3.2 (slice 8d) member repayment-proposal surface. The response models all 15
        // MemberRepaymentProposalResponse properties (reverse check needs every required field); the
        // request bodies are additionalProperties=false → the forward check is the forbid protection,
        // and the home-currency-only create DTO intentionally omits the optional foreign-currency
        // fields (a subset of the schema). Reject/Withdraw are no-field bodies (the backend requires
        // an empty {} object) — registered so a schema rename reddens the gate.
        Pairing(MemberRepaymentProposalDto::class, "MemberRepaymentProposalResponse"),
        Pairing(MemberRepaymentProposalListResponseDto::class, "MemberRepaymentProposalListResponse"),
        Pairing(MemberRepaymentProposalCreateRequestDto::class, "MemberRepaymentProposalCreateRequest"),
        Pairing(MemberRepaymentProposalConfirmRequestDto::class, "MemberRepaymentProposalConfirmRequest"),
        Pairing(MemberRepaymentProposalRejectRequestDto::class, "MemberRepaymentProposalRejectRequest"),
        Pairing(MemberRepaymentProposalWithdrawRequestDto::class, "MemberRepaymentProposalWithdrawRequest"),
        // ADR-0049 §杠杆③ (slice 3a) NLS repayment-capture inbox. The response models all 7 required
        // RepaymentDraftResponse fields (reverse check); create/confirm bodies are
        // additionalProperties=false → the forward check is the forbid protection, and the
        // home-currency-only create DTO omits the original-currency surface (it does not exist —
        // the capture is CNY-only). Dismiss is a no-field body (the backend requires an empty {}).
        Pairing(RepaymentDraftDto::class, "RepaymentDraftResponse"),
        Pairing(RepaymentDraftListResponseDto::class, "RepaymentDraftListResponse"),
        Pairing(RepaymentDraftCreateRequestDto::class, "RepaymentDraftCreateRequest"),
        Pairing(ExpenseRepaymentDraftCreateRequestDto::class, "ExpenseRepaymentDraftCreateRequest"),
        Pairing(RepaymentDraftConfirmRequestDto::class, "RepaymentDraftConfirmRequest"),
        Pairing(RepaymentDraftDismissRequestDto::class, "RepaymentDraftDismissRequest"),
    )

    // Backend `required` fields a DTO intentionally does NOT model (Android doesn't
    // consume them). Keyed by backend schema name. Anything a schema requires but the
    // DTO omits AND is not listed here is drift → CI red. Populated from a real gate run.
    private val ignoredRequiredFields: Map<String, Set<String>> = mapOf(
        // Bill-split DTOs model only `amount_cents` (the home-currency cents the UI shows);
        // the backend's currency-code fields are intentionally not consumed — bill-split
        // does not surface original-currency detail (ADR-0029, pre-existing). The reverse
        // check surfaced this real omission; revisit if bill-split grows multi-currency UI.
        "BillSplitSentResponse" to setOf("home_currency_code", "original_currency_code"),
        "BillSplitInboxResponse" to setOf("home_currency_code", "original_currency_code"),
    )

    @Test
    fun everyDtoFieldIsBackedByItsOpenApiSchema() {
        val drift = pairs.mapNotNull { p ->
            val orphans = dtoJsonNames(p.dto) - schemaProperties(p.schema)
            if (orphans.isEmpty()) {
                null
            } else {
                "${p.dto.simpleName} → ${p.schema}: @Json fields absent from the backend schema " +
                    "(a backend rename/drop the DTO didn't track): ${orphans.sorted()}"
            }
        }
        assertTrue(
            drift.isEmpty(),
            "Android DTO ↔ OpenAPI contract drift — regenerate the DTO or the snapshot:\n" +
                drift.joinToString("\n"),
        )
    }

    @Test
    fun everyRequiredSchemaFieldIsModeledByItsDto() {
        // Reverse of the parity check above. Moshi silently DROPS extra JSON keys, so a DTO
        // that loses a field the backend still sends (e.g. fx_rate, or a tag conflict token)
        // would stay green under the forward check alone. Here: every backend-`required`
        // field must be a DTO @Json name, or be explicitly allowlisted as not-consumed.
        val gaps = pairs.mapNotNull { p ->
            val missing = schemaRequired(p.schema) - dtoJsonNames(p.dto) - ignoredRequiredFields[p.schema].orEmpty()
            if (missing.isEmpty()) {
                null
            } else {
                "${p.dto.simpleName} → ${p.schema}: required backend fields not modeled by the DTO " +
                    "(add them, or allowlist in ignoredRequiredFields): ${missing.sorted()}"
            }
        }
        assertTrue(
            gaps.isEmpty(),
            "Android DTO misses required OpenAPI fields (silently ignored by Moshi):\n" +
                gaps.joinToString("\n"),
        )
    }

    @Test
    fun eachDtoDecodesASyntheticBackendInstance() {
        for (p in pairs) {
            val json = ANY.toJson(synthesizeSchema(p.schema, mutableSetOf()))
            val decoded = MOSHI.adapter(p.dto.java).fromJson(json)
            assertNotNull(
                decoded,
                "${p.dto.simpleName}: production Moshi could not decode a synthesized ${p.schema}.\n$json",
            )
        }
    }

    @Test
    fun parityCheckRedsOnASimulatedBackendRename() {
        // Self-test the orphan detection: prove it reddens when the backend renames a
        // field the DTO still references (the exact failure mode this gate exists for),
        // and stays green when the names align — so a green run above is meaningful.
        val dtoNames = dtoJsonNames(TagDetailDto::class) // public_id, name, row_version
        assertEquals(setOf("row_version"), dtoNames - setOf("public_id", "name", "row_version_renamed"))
        assertTrue((dtoNames - setOf("public_id", "name", "row_version")).isEmpty())
    }

    // ── reflection: the DTO's wire names (@param:Json name, else the property name) ──
    private fun dtoJsonNames(dto: KClass<*>): Set<String> {
        val ctor = dto.primaryConstructor ?: error("${dto.simpleName} has no primary constructor")
        return ctor.parameters.map { param ->
            param.annotations.filterIsInstance<Json>().firstOrNull()?.name ?: param.name!!
        }.toSet()
    }

    @Suppress("UNCHECKED_CAST")
    private fun schemaProperties(name: String): Set<String> {
        val schema = SCHEMAS[name] as? Map<String, Any?>
            ?: error("schema '$name' missing from the OpenAPI snapshot — fix the mapping in `pairs`")
        return (schema["properties"] as? Map<String, Any?>)?.keys.orEmpty()
    }

    @Suppress("UNCHECKED_CAST")
    private fun schemaRequired(name: String): Set<String> {
        val schema = SCHEMAS[name] as? Map<String, Any?>
            ?: error("schema '$name' missing from the OpenAPI snapshot — fix the mapping in `pairs`")
        return (schema["required"] as? List<String>)?.toSet().orEmpty()
    }

    // ── generative synthesis: a minimal typed instance from a schema's declared types ──
    @Suppress("UNCHECKED_CAST")
    private fun synthesizeSchema(schemaName: String, seen: MutableSet<String>): Map<String, Any?> {
        val schema = SCHEMAS[schemaName] as? Map<String, Any?> ?: error("schema '$schemaName' missing")
        val props = schema["properties"] as? Map<String, Any?> ?: return emptyMap()
        return props.mapValues { (_, raw) -> synthesizeValue(raw as Map<String, Any?>, seen) }
    }

    @Suppress("UNCHECKED_CAST")
    private fun synthesizeValue(node: Map<String, Any?>, seen: MutableSet<String>): Any? {
        (node["\$ref"] as? String)?.let { ref ->
            val name = ref.substringAfterLast('/')
            if (!seen.add(name)) return null // cycle guard
            return synthesizeSchema(name, seen).also { seen.remove(name) }
        }
        (node["anyOf"] as? List<Map<String, Any?>>)?.let { options ->
            val nonNull = options.filter { (it["type"] as? String) != "null" }
            val pick = nonNull.firstOrNull() ?: return null
            // Bound the synthesis: a nullable nested object/$ref → emit null rather than
            // recursing (the scalar fields, where the FX rename hazard lives, are exercised).
            val objectLike = pick.containsKey("\$ref") || (pick["type"] as? String) == "object"
            val nullable = options.any { (it["type"] as? String) == "null" }
            return if (objectLike && nullable) null else synthesizeValue(pick, seen)
        }
        return when (node["type"] as? String) {
            "string" -> when (node["format"] as? String) {
                "date" -> "2026-01-01"
                "date-time" -> "2026-01-01T00:00:00Z"
                else -> "x"
            }
            "integer" -> 1
            "number" -> 1.5
            "boolean" -> true
            "array" -> emptyList<Any?>()
            "object" -> emptyMap<String, Any?>()
            else -> null
        }
    }

    private companion object {
        // The SAME builder ApiClient/NetworkErrorHandler use in production (plain
        // reflection, no custom adapters), so the round-trip is faithful to runtime.
        val MOSHI: Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
        val ANY = MOSHI.adapter(Any::class.java)

        @Suppress("UNCHECKED_CAST")
        val SCHEMAS: Map<String, Any?> = run {
            val root = ANY.fromJson(locateOpenApiSnapshot().readText()) as Map<String, Any?>
            (root["components"] as Map<String, Any?>)["schemas"] as Map<String, Any?>
        }

        private fun locateOpenApiSnapshot(): File {
            // JVM unit tests run with a module-relative working dir; walk up to the repo
            // root that holds the snapshot. Fail loud (never skip) so the gate can't no-op.
            var dir: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
            while (dir != null) {
                val candidate = File(dir, "docs/architecture/openapi_contract.json")
                if (candidate.exists()) return candidate
                dir = dir.parentFile
            }
            error("openapi_contract.json not found walking up from ${System.getProperty("user.dir")}")
        }
    }
}
